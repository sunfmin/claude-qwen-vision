#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = ["mlx-vlm>=0.6"]
# ///
"""qwen_vision_local — 离线图片理解：用本地 MLX 版 Qwen3-VL 看图。

在线 qwen3.8-max 不可用时（qwen_vision.py 的自动回退），本脚本用
HuggingFace 缓存里的本地模型把图片转成文本，全程不发任何网络请求。

模型注册表（都在 HF cache 中，缺哪个按 repo_id 去下）：
  30b  mlx-community/Qwen3-VL-30B-A3B-Instruct-4bit  ← 默认，质量最好
  8b   mlx-community/Qwen3-VL-8B-Instruct-8bit        ← 加载更快、省内存

用法：
  uv run --no-project /绝对/路径/qwen_vision_local.py IMG [IMG...] \
      [--prompt "…"] [--model 30b|8b] [--max-tokens N]

首次运行 uv 会用 PEP 723 声明装 mlx-vlm（依赖已在本地 uv 缓存），模型从
HF cache 直接加载，不走网络。加载耗时随模型大小而异（30b 约 1–2 分钟），
之后的生成很快。--model 指定的模型本地缺失时自动退到另一个。

输出保证：成功时 stdout 一定有内容；模型目录缺失、模型返回空文本、文件
出错，一律向 stderr 报错并以非零码退出——绝不静默输出空行。
"""
import argparse
import os
import sys
import time
from pathlib import Path

# 模型注册表：事实的唯一归宿，CLI 选项从这里派生。
MODELS = {
    "30b": "mlx-community/Qwen3-VL-30B-A3B-Instruct-4bit",
    "8b": "mlx-community/Qwen3-VL-8B-Instruct-8bit",
}
DEFAULT_MODEL = "30b"
DEFAULT_PROMPT = "Describe this image in detail, including any text visible in it."
MAX_TOKENS = 1024

# 离线是硬要求：在 import mlx_vlm 之前关掉一切网络回退。
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")


def fail(msg: str) -> None:
    print(f"qwen_vision_local: {msg}", file=sys.stderr)
    sys.exit(1)


def snapshot_dir(repo_id: str) -> Path | None:
    """HF cache 里某 repo 的最新本地快照目录；缺失或不完整则 None。"""
    hf_home = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
    org, name = repo_id.split("/", 1)
    snapshots = hf_home / "hub" / f"models--{org}--{name}" / "snapshots"
    candidates = [p for p in snapshots.iterdir() if p.is_dir()] if snapshots.is_dir() else []
    if not candidates:
        return None
    latest = max(candidates, key=lambda p: p.stat().st_mtime)
    if not (latest / "config.json").exists() or not list(latest.glob("*.safetensors")):
        return None
    return latest


def resolve_model(choice: str) -> tuple[str, Path]:
    """首选 --model 指定的模型；本地缺失时按注册表顺序退到另一个。"""
    order = [choice] + [k for k in MODELS if k != choice]
    tried = []
    for key in order:
        snap = snapshot_dir(MODELS[key])
        if snap is not None:
            return MODELS[key], snap
        tried.append(MODELS[key])
    fail(
        "本地 HF cache 里找不到可用的 Qwen3-VL 模型，找过: "
        + ", ".join(tried)
        + "。请先下载其中一个。"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="本地 Qwen3-VL（MLX）看图，离线输出文本")
    ap.add_argument("paths", nargs="+", help="图片文件路径（可多个）")
    ap.add_argument("--prompt", default=DEFAULT_PROMPT, help="看图的指令")
    ap.add_argument("--model", choices=tuple(MODELS), default=DEFAULT_MODEL,
                    help=f"本地模型（默认 {DEFAULT_MODEL}；本地缺失时自动退到另一个）")
    ap.add_argument("--max-tokens", type=int, default=MAX_TOKENS,
                    help=f"输出 token 上限（默认 {MAX_TOKENS}）")
    args = ap.parse_args()

    for p in args.paths:
        if not Path(p).is_file():
            fail(f"读图失败 {p}: 文件不存在")

    from mlx_vlm import generate, load
    from mlx_vlm.prompt_utils import apply_chat_template

    repo_id, snap = resolve_model(args.model)
    t0 = time.time()
    print(f"qwen_vision_local: 加载本地模型 {repo_id} (snapshot {snap.name})…", file=sys.stderr)
    model, processor = load(str(snap))
    print(f"qwen_vision_local: 模型加载完成 {time.time() - t0:.1f}s，开始生成…", file=sys.stderr)

    prompt = apply_chat_template(processor, model.config, args.prompt, num_images=len(args.paths))
    result = generate(
        model, processor, prompt,
        image=args.paths, max_tokens=args.max_tokens, temperature=0.0,
    )
    text = result.text.strip()
    if not text:
        fail("本地模型返回空文本——请重试，或换 --model")
    print(f"qwen_vision_local: 生成完成，共 {time.time() - t0:.1f}s", file=sys.stderr)
    print(text)


if __name__ == "__main__":
    main()
