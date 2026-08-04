#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""user_prompt_hook — UserPromptSubmit hook：粘贴的图片 → qwen 描述 → 注入会话。

目标场景：会话模型不支持视觉（如 DeepSeek），用户 ⌘V 粘贴图片。
本 hook 在每次用户消息提交时检查 prompt 文本里的 [Image #N] 标记（粘贴的图
在输入框/消息里就是这个占位符），取到图后用 qwen3.8-max 描述，把描述文本以
additionalContext 注入，模型就能基于文字继续回答。

原则：绝不 block 用户消息 —— 任何失败（没图、取不到字节、qwen 报错、探测失败）
都打印 {} 静默放行。约定：
  - 模型支持视觉（check_vision.py 判定）→ 放行，不浪费 qwen
  - 模型硬不支持（NO_VISION_HARD，图会让整轮 400）→ 放行（注入也救不了）
  - 取图：$CLAUDE_CONFIG_DIR/image-cache/<session_id>/ 优先（快），
    找不到再轮询 transcript_path（文档化路径，可能异步写入，最多等 4s）
安装（写 settings.json）见同目录 install-hook.sh。
"""
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import qwen_vision  # noqa: E402

IMAGE_MARKER = re.compile(r"\[Image #\d+\]")
DESCRIBE_PROMPT = (
    "请完整描述这张图片：整体内容、布局、颜色和其中的对象。"
    "如果是截图（报错、界面、聊天记录、文档等），请逐字还原所有可见文字并说明上下文。"
    "用中文回答，尽量详细。"
)
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")


def image_cache_files(session_id: str) -> list[str]:
    cfg = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    d = os.path.join(cfg, "image-cache", session_id)
    if not os.path.isdir(d):
        return []
    return sorted(
        os.path.join(d, f) for f in os.listdir(d) if f.lower().endswith(_IMAGE_EXTS)
    )


def last_user_image_blocks(transcript_path: str) -> list[dict]:
    """从 transcript JSONL 找最后一条带 image content block 的用户消息（含 base64）。"""
    if not transcript_path or not os.path.isfile(transcript_path):
        return []
    blocks: list[dict] = []
    with open(transcript_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = rec.get("message") or {}
            if msg.get("role") != "user":
                continue
            content = msg.get("content")
            if isinstance(content, list):
                img = [b for b in content if isinstance(b, dict) and b.get("type") == "image"]
                if img:
                    blocks = img
    return blocks


def check_vision_verdict() -> str:
    """复用 check_vision.py（同一目录，缓存共享）。"""
    cv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "check_vision.py")
    r = subprocess.run([sys.executable, cv_path], capture_output=True, text=True)
    return r.stdout.strip()


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        print("{}")
        return
    prompt = data.get("prompt") or ""
    if not IMAGE_MARKER.search(prompt):
        print("{}")
        return
    try:
        verdict = check_vision_verdict()
        if verdict != "NO_VISION_SILENT":
            print("{}")
            return

        blocks: list[dict] = []
        for path in image_cache_files(data.get("session_id", "")):
            blocks.append(qwen_vision.image_block_from_file(path))
        if not blocks:
            deadline = time.time() + 4.0
            while time.time() < deadline:
                blocks = last_user_image_blocks(data.get("transcript_path"))
                if blocks:
                    break
                time.sleep(0.2)
        if not blocks:
            print("{}")
            return

        desc = qwen_vision.call_qwen(blocks, DESCRIBE_PROMPT, None)
        context = (
            "【claude-qwen-vision】用户消息里附了一张图片，但当前会话模型不支持视觉、看不到图。"
            "以下是对图片的文字描述（用 qwen3.8-max 生成），请把它当作图片的真实内容来理解并回答用户的问题：\n\n"
            + desc
        )
        print(json.dumps(
            {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": context}},
            ensure_ascii=False,
        ))
    except Exception:
        print("{}")


if __name__ == "__main__":
    main()
