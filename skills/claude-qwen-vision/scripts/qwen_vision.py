#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""qwen_vision — 把图片交给 qwen3.8-max 理解，输出文本描述。

自包含脚本：只用标准库（dependencies 为空），从任意 cwd 直接
`uv run --no-project /绝对/路径/qwen_vision.py …` 即可执行，不需要 cd 到
脚本所在目录，也不依赖仓库里任何其他文件。

用法：
  1. 图片文件路径:    qwen_vision.py /path/to/image.png [更多路径...] [--prompt "…"]
  2. base64 输入:      qwen_vision.py --base64 <data> --media-type image/png [--prompt "…"]

凭证从 mytokens 的 qwen profile 读取（ANTHROPIC_BASE_URL / ANTHROPIC_MODEL /
ANTHROPIC_AUTH_TOKEN），绝不硬编码、绝不打印。默认走 token-plan 账号，可
--account paygo 切按量付费。响应中的 thinking 块会被丢弃，只输出最终文本。

输出保证：成功时 stdout 一定有内容；qwen 返回空文本 / 响应被截断 / 网络
或文件出错，一律向 stderr 报错并以非零码退出，绝不静默输出空行。
"""
import argparse
import base64
import json
import mimetypes
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

DEFAULT_PROMPT = "Describe this image in detail, including any text visible in it."
# 多张大图 + 长输出时 2048 不够（会整段截断）。qwen3.8-max 支持 8192。
MAX_TOKENS = 8192
REQUEST_TIMEOUT = 300  # 秒；多图时上传与生成都慢，留足余量


def fail(msg: str) -> None:
    print(f"qwen_vision: {msg}", file=sys.stderr)
    sys.exit(1)


def mytokens_get(field: str, account: str | None) -> str:
    if shutil.which("mytokens") is None:
        fail("找不到 mytokens CLI——先 `npx skills add sunfmin/mytokens -g` 安装并配置 qwen profile")
    cmd = ["mytokens", "get", "qwen"]
    if account:
        cmd += ["--account", account]
    cmd += ["--field", field]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        fail(f"mytokens get qwen --field {field} 失败: {r.stderr.strip() or 'secret 不存在'}")
    out = r.stdout.strip()
    if not out:
        fail(f"mytokens get qwen --field {field} 返回空——qwen profile 没配这个字段")
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


def call_qwen(image_blocks: list[dict], prompt: str, account: str | None) -> str:
    base = mytokens_get("ANTHROPIC_BASE_URL", account)
    model = mytokens_get("ANTHROPIC_MODEL", account)
    token = mytokens_get("ANTHROPIC_AUTH_TOKEN", account)
    payload = {
        "model": model,
        "max_tokens": MAX_TOKENS,
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
        fail(f"qwen API 错误 {e.code}: {body[:500]}")
    except urllib.error.URLError as e:
        fail(f"qwen API 请求失败: {e.reason}")

    content = data.get("content") or []
    texts = [b.get("text", "") for b in content if b.get("type") == "text"]
    out = "\n".join(t for t in texts if t).strip()
    if not out:
        kinds = ",".join(sorted({b.get("type", "?") for b in content})) or "空"
        fail(f"qwen 返回了空文本（content 块类型: {kinds}）——模型没吐出任何内容，请重试或换 --account")

    stop = data.get("stop_reason")
    if stop == "max_tokens":
        out += (
            f"\n\n[注意：响应达到 max_tokens={MAX_TOKENS} 上限被截断，"
            f"图片内容可能没读完，请拆成单图重跑]"
        )
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="用 qwen3.8-max 理解图片，输出文本（凭证来自 mytokens）")
    ap.add_argument("paths", nargs="*", help="图片文件路径（可多个，相对路径按当前 cwd 解析）")
    ap.add_argument("--base64", help="直接传 base64 图片数据（配合 --media-type）")
    ap.add_argument("--media-type", default="image/png", help="base64 输入的媒体类型")
    ap.add_argument("--prompt", default=DEFAULT_PROMPT, help="让 qwen 看图的指令")
    ap.add_argument("--account", help="mytokens qwen profile 账号（默认 qwen，可传 paygo）")
    args = ap.parse_args()

    blocks = []
    if args.base64:
        blocks.append({"type": "image", "source": {"type": "base64", "media_type": args.media_type, "data": args.base64}})
    for p in args.paths:
        blocks.append(image_block_from_file(p))
    if not blocks:
        ap.error("至少要给一个图片路径或 --base64")

    print(call_qwen(blocks, args.prompt, args.account))


if __name__ == "__main__":
    main()
