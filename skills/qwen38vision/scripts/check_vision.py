#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""check_vision — 探测会话模型是否支持图片，打印 VISION / NO_VISION_HARD / NO_VISION_SILENT。

Anthropic 兼容端点不暴露模型能力标志，只能经验探测：发一张 1x1 测试图，
按响应分类：
  - 4xx (unknown variant 'image' 之类) → NO_VISION_HARD   图会让整轮 400 失败
  - 200 但 "can't see / [Unsupported Image]" → NO_VISION_SILENT  图被静默替换
  - 200 且答出 "OK"                      → VISION           真能看图

端点优先级：当前进程环境 ANTHROPIC_BASE_URL/MODEL + 令牌 → mytokens deepseek
→ mytokens qwen。结果按 (base, model) 哈希缓存到 $TMPDIR，避免每次探测。

用法:
  check_vision.py                探测当前会话模型（hook / skill 默认路径）
  check_vision.py --profile NAME [--account A]   探测 mytokens 里的 profile
  check_vision.py --refresh      忽略缓存重新探测
"""
import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

# 32x32 纯色 PNG —— 注意：qwen 端点要求宽高 > 10px，1x1 会 400
TEST_IMAGE_B64 = "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAIAAAD8GO2jAAAAOklEQVR4nO3RQREAQAjDwHJC8C8FWSchfPhlBZSZUNOdS+90PR5Y8AfIRMhEyETIRMhEyETIRMhEIR/gBQFERyvVpAAAAABJRU5ErkJggg=="
PROBE_PROMPT = "Reply with exactly 'OK' if you can see the image."

BLIND_MARKERS = (
    "can't see", "cannot see", "unsupported image", "unable to view", "cannot view",
    "don't have vision", "no vision", "not support image", "doesn't support",
    "看不到", "无法查看", "无法看到", "不支持图片",
)


def cache_path(base: str, model: str) -> str:
    key = hashlib.sha256(f"{base}|{model}".encode()).hexdigest()[:16]
    return os.path.join(os.environ.get("TMPDIR", "/tmp"), f"qwen38vision_vision_{key}")


def env_or_none(name: str) -> str | None:
    v = os.environ.get(name)
    return v.strip() if v and v.strip() else None


def mytokens_get(field: str, profile: str, account: str | None) -> str:
    cmd = ["mytokens", "get", profile]
    if account:
        cmd += ["--account", account]
    cmd += ["--field", field]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"mytokens get {profile} --field {field} 失败: {r.stderr.strip() or 'secret 不存在'}")
    return r.stdout.strip()


# 已知模型快速路径：完全确定的类型直接给结论，不探测、不花钱。
# 注意：qwen 家族不能用名字判断（qwen3.8-max 无 vl 却支持视觉；本地 omlx 部署
# 的 qwen 会静默丢图）→ 一律走探测。deepseek-vl 是例外，先排除。
FAST_BLIND = ("deepseek",)
FAST_VISION = ("claude", "gpt-4o", "gpt-4.1", "gemini", "glm-4v", "qwen-vl", "qwen3-vl", "vision")


def fast_verdict(base: str, model: str) -> str | None:
    blob = f"{base} {model}".lower()
    if "deepseek" in blob and "vl" not in model.lower():
        return "NO_VISION_SILENT"
    for m in FAST_VISION:
        if m in blob:
            return "VISION"
    return None


def resolve_endpoint(args) -> tuple[str, str, str]:
    """返回 (base_url, model, token) — 优先环境变量，其次 mytokens。"""
    if args.profile:
        acct = args.account
        base = mytokens_get("ANTHROPIC_BASE_URL", args.profile, acct)
        model = mytokens_get("ANTHROPIC_MODEL", args.profile, acct)
        token = mytokens_get("ANTHROPIC_AUTH_TOKEN", args.profile, acct)
        return base, model, token
    base = env_or_none("ANTHROPIC_BASE_URL")
    model = env_or_none("ANTHROPIC_MODEL")
    token = env_or_none("ANTHROPIC_AUTH_TOKEN") or env_or_none("ANTHROPIC_API_KEY")
    if base and model and token:
        return base, model, token
    # 环境里拿不到令牌时退回 mytokens deepseek
    base = mytokens_get("ANTHROPIC_BASE_URL", "deepseek", None)
    model = mytokens_get("ANTHROPIC_MODEL", "deepseek", None)
    token = mytokens_get("ANTHROPIC_AUTH_TOKEN", "deepseek", None)
    return base, model, token


def probe(base: str, model: str, token: str) -> str:
    payload = {
        "model": model,
        "max_tokens": 128,
        "messages": [{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": TEST_IMAGE_B64}},
            {"type": "text", "text": PROBE_PROMPT},
        ]}],
    }
    req = urllib.request.Request(
        base.rstrip("/") + "/v1/messages",
        data=json.dumps(payload).encode(),
        headers={"x-api-key": token, "anthropic-version": "2023-06-01", "content-type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        if 400 <= e.code < 500:
            return "NO_VISION_HARD"
        sys.exit(f"探测请求失败 {e.code}: {body[:300]}")
    text = " ".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text").lower()
    # 没有 text 块（思考被截断 / 静默丢弃）→ 按盲处理，对 hook 更安全
    if not text:
        return "NO_VISION_SILENT"
    if any(m in text for m in BLIND_MARKERS):
        return "NO_VISION_SILENT"
    return "VISION"


def main() -> None:
    ap = argparse.ArgumentParser(description="探测模型是否支持图片")
    ap.add_argument("--profile", help="mytokens profile 名（默认用当前进程环境）")
    ap.add_argument("--account", help="mytokens profile 账号")
    ap.add_argument("--refresh", action="store_true", help="忽略缓存")
    args = ap.parse_args()

    base, model, token = resolve_endpoint(args)
    fv = fast_verdict(base, model)
    if fv:
        print(fv)
        return
    cp = cache_path(base, model)
    if not args.refresh and os.path.isfile(cp):
        verdict = open(cp, encoding="utf-8").read().strip()
        if verdict in ("VISION", "NO_VISION_HARD", "NO_VISION_SILENT"):
            print(verdict)
            return
    verdict = probe(base, model, token)
    with open(cp, "w", encoding="utf-8") as f:
        f.write(verdict)
    print(verdict)


if __name__ == "__main__":
    main()
