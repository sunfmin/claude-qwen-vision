#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""qwen_vision — 把图片交给 qwen3.8-max 理解，输出文本描述；在线不可用时自动回退本地模型。

自包含脚本：只用标准库（dependencies 为空），从任意 cwd 直接
`uv run --no-project /绝对/路径/qwen_vision.py …` 即可执行，不需要 cd 到
脚本所在目录，也不依赖仓库里任何其他文件（本地回退会调用同目录下的
qwen_vision_local.py，缺失时明确报错）。

用法：
  1. 图片文件路径:    qwen_vision.py /path/to/image.png [更多路径...] [--prompt "…"] [--max-tokens N]
  2. base64 输入:      qwen_vision.py --base64 <data> --media-type image/png [--prompt "…"] [--max-tokens N]

凭证从 mytokens 的 qwen profile 读取（ANTHROPIC_BASE_URL / ANTHROPIC_MODEL /
ANTHROPIC_AUTH_TOKEN），绝不硬编码、绝不打印。默认走 token-plan 账号，可
--account paygo 切按量付费。请求显式关掉 thinking（该网关上思考无上界、
会吃光输出预算），只输出最终文本。

在线回退：mytokens 缺失、凭证读取失败、网络错误或 qwen 返回空文本，一律
自动改跑本地 Qwen3-VL（MLX，模型在 HF cache 里，离线可用）。回退过程写
stderr，stdout 保持只有图片描述。--no-local-fallback 关闭回退，--local-model
选本地模型（默认 30b）。

输出保证：成功时 stdout 一定有内容；文件出错、回退也被关闭、或本地模型也
失败，才向 stderr 报错并以非零码退出——绝不静默输出空行。
"""
import argparse
import base64
import json
import mimetypes
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_PROMPT = "Describe this image in detail, including any text visible in it."
# max_tokens 是端点必填参数（省略直接 400），实测接受 ≥524288，默认给足余量，
# 可用 --max-tokens 覆盖。注意：token-plan 网关上 qwen3.8-max 的 thinking 无上界，
# 会吃光整个输出预算（实测 8192 全被 thinking 占掉、text 一个 token 都不剩），
# 因此 payload 里显式关掉 thinking（见 call_qwen）。
MAX_TOKENS = 131072
REQUEST_TIMEOUT = 300  # 秒；多图时上传与生成都慢，留足余量


class OnlineUnavailable(RuntimeError):
    """在线 qwen 服务不可用（凭证、网络、空响应都算），触发本地回退。"""


def fail(msg: str) -> None:
    print(f"qwen_vision: {msg}", file=sys.stderr)
    sys.exit(1)


def mytokens_get(field: str, account: str | None) -> str:
    if shutil.which("mytokens") is None:
        raise OnlineUnavailable(
            "找不到 mytokens CLI——先 `npx skills add sunfmin/mytokens -g` 安装并配置 qwen profile"
        )
    cmd = ["mytokens", "get", "qwen"]
    if account:
        cmd += ["--account", account]
    cmd += ["--field", field]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise OnlineUnavailable(
            f"mytokens get qwen --field {field} 失败: {r.stderr.strip() or 'secret 不存在'}"
        )
    out = r.stdout.strip()
    if not out:
        raise OnlineUnavailable(f"mytokens get qwen --field {field} 返回空——qwen profile 没配这个字段")
    return out


def media_type_for(path: str) -> str:
    t = mimetypes.guess_type(path)[0]
    return t if t and t.startswith("image/") else "image/png"


def image_block_from_file(path: str) -> dict:
    try:
        with open(path, "rb") as f:
            data = base64.b64encode(f.read()).decode()
    except OSError as e:
        fail(f"读图失败 {path}: {e}")
    return {"type": "image", "source": {"type": "base64", "media_type": media_type_for(path), "data": data}}


def call_qwen(image_blocks: list[dict], prompt: str, account: str | None, max_tokens: int) -> str:
    base = mytokens_get("ANTHROPIC_BASE_URL", account)
    model = mytokens_get("ANTHROPIC_MODEL", account)
    token = mytokens_get("ANTHROPIC_AUTH_TOKEN", account)
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        # 订阅网关上 qwen3.8-max 的 thinking 无上界：一段思考就能吃满整个
        # max_tokens，text 一个 token 都不剩。显式关掉后输出立即可用
        # （实测 stop_reason=end_turn、无 thinking 块）。
        "thinking": {"type": "disabled"},
        "messages": [{"role": "user", "content": image_blocks + [{"type": "text", "text": prompt}]}],
    }
    req = urllib.request.Request(
        base.rstrip("/") + "/v1/messages",
        data=json.dumps(payload).encode(),
        headers={
            "x-api-key": token,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise OnlineUnavailable(f"qwen API 错误 {e.code}: {body[:500]}")
    except urllib.error.URLError as e:
        raise OnlineUnavailable(f"qwen API 请求失败: {e.reason}")

    content = data.get("content") or []
    texts = [b.get("text", "") for b in content if b.get("type") == "text"]
    out = "\n".join(t for t in texts if t).strip()
    if not out:
        kinds = ",".join(sorted({b.get("type", "?") for b in content})) or "空"
        raise OnlineUnavailable(f"qwen 返回了空文本（content 块类型: {kinds}）——模型没吐出任何内容")

    stop = data.get("stop_reason")
    if stop == "max_tokens":
        out += (
            f"\n\n[注意：响应达到 max_tokens={max_tokens} 上限被截断，"
            f"图片内容可能没读完，请拆成单图重跑]"
        )
    return out


LOCAL_MODELS = ("30b", "8b")


def run_local_fallback(args, reason: str) -> str:
    """在线失败时改跑同目录下的 qwen_vision_local.py，返回其 stdout。"""
    if shutil.which("uv") is None:
        fail("本地回退需要 uv（uv run 执行 qwen_vision_local.py），但 PATH 里找不到 uv")
    local_script = Path(__file__).resolve().parent / "qwen_vision_local.py"
    if not local_script.is_file():
        fail(f"本地回退脚本缺失: {local_script}——请补上同目录的 qwen_vision_local.py")

    paths = [str(Path(p).resolve()) for p in args.paths]
    if args.base64:  # 本地脚本只收文件路径，base64 落盘到临时文件
        suffix = mimetypes.guess_extension(args.media_type) or ".png"
        with tempfile.NamedTemporaryFile(prefix="qwen_vision_", suffix=suffix, delete=False) as f:
            f.write(base64.b64decode(args.base64))
            paths.append(f.name)

    print(f"qwen_vision: 在线服务不可用（{reason}），改用本地模型 Qwen3-VL…", file=sys.stderr)
    cmd = ["uv", "run", "--no-project", str(local_script), *paths, "--prompt", args.prompt,
           "--model", args.local_model]
    if args.max_tokens != MAX_TOKENS:  # 用户显式设了上限才转发；在线默认值对本地模型不适用
        cmd += ["--max-tokens", str(args.max_tokens)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        fail(f"本地模型回退失败: {r.stderr.strip() or r.stdout.strip() or '未知错误'}")
    out = r.stdout.strip()
    if not out:
        fail("本地模型回退返回空文本")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="用 qwen3.8-max 理解图片，输出文本（凭证来自 mytokens，在线不可用时回退本地模型）")
    ap.add_argument("paths", nargs="*", help="图片文件路径（可多个，相对路径按当前 cwd 解析）")
    ap.add_argument("--base64", help="直接传 base64 图片数据（配合 --media-type）")
    ap.add_argument("--media-type", default="image/png", help="base64 输入的媒体类型")
    ap.add_argument("--prompt", default=DEFAULT_PROMPT, help="让 qwen 看图的指令")
    ap.add_argument("--account", help="mytokens qwen profile 账号（默认 qwen，可传 paygo）")
    ap.add_argument("--max-tokens", type=int, default=MAX_TOKENS,
                    help=f"输出 token 上限（含 thinking，默认 {MAX_TOKENS}；端点实测接受 ≥524288）")
    ap.add_argument("--no-local-fallback", action="store_true",
                    help="在线不可用时直接报错退出，不跑本地模型")
    ap.add_argument("--local-model", choices=LOCAL_MODELS, default="30b",
                    help=f"本地回退用哪个模型（默认 30b；30b 质量好，8b 加载快）")
    args = ap.parse_args()

    blocks = []
    if args.base64:
        blocks.append({"type": "image", "source": {"type": "base64", "media_type": args.media_type, "data": args.base64}})
    for p in args.paths:
        blocks.append(image_block_from_file(p))
    if not blocks:
        ap.error("至少要给一个图片路径或 --base64")

    try:
        out = call_qwen(blocks, args.prompt, args.account, args.max_tokens)
    except OnlineUnavailable as e:
        if args.no_local_fallback:
            fail(str(e))
        out = run_local_fallback(args, str(e))
    print(out)


if __name__ == "__main__":
    main()
