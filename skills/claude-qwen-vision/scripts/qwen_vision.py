#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""qwen_vision — 把图片交给 qwen3.8-max 理解，输出文本描述。

会话模型（如 DeepSeek）看不到图片时，用它把图转成文本：
  1. 图片文件路径:    qwen_vision.py /path/to/image.png [更多路径...] [--prompt "…"]
  2. base64 输入:      qwen_vision.py --base64 <data> --media-type image/png [--prompt "…"]

凭证从 mytokens 的 qwen profile 读取（ANTHROPIC_BASE_URL / ANTHROPIC_MODEL /
ANTHROPIC_AUTH_TOKEN），绝不硬编码、绝不打印。默认走 token-plan 账号，可
--account paygo 切按量付费。响应中的 thinking 块会被丢弃，只输出最终文本。
"""
import argparse
import base64
import json
import mimetypes
import subprocess
import sys
import urllib.error
import urllib.request

DEFAULT_PROMPT = "Describe this image in detail, including any text visible in it."


def mytokens_get(field: str, account: str | None) -> str:
    cmd = ["mytokens", "get", "qwen"]
    if account:
        cmd += ["--account", account]
    cmd += ["--field", field]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"mytokens get qwen --field {field} 失败: {r.stderr.strip() or 'secret 不存在'}")
    return r.stdout.strip()


def media_type_for(path: str) -> str:
    t = mimetypes.guess_type(path)[0]
    return t if t and t.startswith("image/") else "image/png"


def image_block_from_file(path: str) -> dict:
    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode()
    return {"type": "image", "source": {"type": "base64", "media_type": media_type_for(path), "data": data}}


def call_qwen(image_blocks: list[dict], prompt: str, account: str | None) -> str:
    base = mytokens_get("ANTHROPIC_BASE_URL", account)
    model = mytokens_get("ANTHROPIC_MODEL", account)
    token = mytokens_get("ANTHROPIC_AUTH_TOKEN", account)
    payload = {
        "model": model,
        "max_tokens": 2048,
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
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        sys.exit(f"qwen API 错误 {e.code}: {body[:500]}")
    texts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
    return "\n".join(t for t in texts if t)


def main() -> None:
    ap = argparse.ArgumentParser(description="用 qwen3.8-max 理解图片，输出文本（凭证来自 mytokens）")
    ap.add_argument("paths", nargs="*", help="图片文件路径（可多个）")
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
