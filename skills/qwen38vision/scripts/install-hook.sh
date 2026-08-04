#!/usr/bin/env bash
# install-hook.sh — 把 qwen38vision 的 UserPromptSubmit hook 合并进 settings.json。
#
# 作用：用户 ⌘V 粘贴图片时，自动用 qwen3.8-max 把图转成文字描述注入会话，
#       DeepSeek 等无视觉模型就能"看到"图。重复运行幂等，改前备份。
#
# 用法: bash install-hook.sh [--config-dir DIR]
#   默认写入 $CLAUDE_CONFIG_DIR/settings.json（未设置时 ~/.claude/settings.json）。
#   注意：CLAUDE_CONFIG_DIR 指向哪，hook 就装到哪 —— ~/.csk 的会话要单独装。
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOK_SCRIPT="$SCRIPT_DIR/user_prompt_hook.py"
[ -f "$HOOK_SCRIPT" ] || { echo "找不到 $HOOK_SCRIPT" >&2; exit 1; }

CFG_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
if [ "${1:-}" = --config-dir ]; then
  CFG_DIR="$2"
fi
SETTINGS="$CFG_DIR/settings.json"

command -v uv >/dev/null 2>&1 || { echo "需要 uv（hook 命令用 uv run 跑脚本）" >&2; exit 1; }

python3 - "$HOOK_SCRIPT" "$SETTINGS" <<'PY'
import json, os, sys
hook_script, settings_path = sys.argv[1], sys.argv[2]
settings = {}
if os.path.isfile(settings_path):
    with open(settings_path, encoding="utf-8") as f:
        settings = json.load(f)
settings.setdefault("hooks", {}).setdefault("UserPromptSubmit", [])
entry = {"matcher": "*", "hooks": [{"type": "command", "command": f"uv run --quiet --no-project {hook_script}", "timeout": 30}]}
existing = settings["hooks"]["UserPromptSubmit"]
if any(e.get("hooks", [{}])[0].get("command") == entry["hooks"][0]["command"] for e in existing if e.get("hooks")):
    print(f"hook 已存在，跳过（{settings_path}）")
    sys.exit(0)
existing.append(entry)
if os.path.isfile(settings_path):
    os.rename(settings_path, settings_path + ".bak")
os.makedirs(os.path.dirname(settings_path), exist_ok=True)
with open(settings_path, "w", encoding="utf-8") as f:
    json.dump(settings, f, ensure_ascii=False, indent=2)
    f.write("\n")
print(f"已写入 {settings_path}（原文件备份为 {settings_path}.bak）")
PY
echo "完成：粘贴的图片会被 qwen3.8-max 自动转成文字注入会话（卸载：把 UserPromptSubmit 里对应命令删掉即可）"
