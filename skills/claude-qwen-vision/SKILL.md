---
name: claude-qwen-vision
description: >
  Handles images the session model cannot see (e.g. DeepSeek): when the user's message contains
  an image — pasted into the terminal (the [Image #N] placeholder) or an image file path — convert
  it to text with qwen3.8-max via scripts/qwen_vision.py (mytokens, Anthropic-compatible) and
  answer from that text instead of trying to view the image directly. Triggers — 用户贴图/截图/
  paste an image, 「看下这张图」「读出图里的文字」「图片在 xxx.png」/analyze or describe this image.
  If user_prompt_hook is installed, pasted images arrive already described — skip.
---

# claude-qwen-vision — 给看不到图的模型补上视觉

DeepSeek 等模型收不到/读不懂图片。本 skill 用 mytokens 里的 `qwen` profile
（qwen3.8-max，阿里云百炼 Anthropic 兼容端点）把图片转成文本，模型基于文本继续推理。

## 什么时候用

用户消息里有图片，且图片内容当前无法直接理解：

| 图片来源 | 怎么处理 |
|---|---|
| prompt 里带图片文件路径（「图片在 /path/x.png」） | 直接跑 `qwen_vision.py` |
| 粘贴进终端的图（消息里出现 `[Image #N]` 或图片内容块） | 已装 hook → 描述已自动注入，直接用；未装 → 请用户把图存成文件给路径 |
| 不确定模型能不能看图 | 先跑 `check_vision.py`（环境变量快速路径 + 探测缓存） |

**先确认模型确实看不到图**，避免浪费：`uv run --quiet --no-project scripts/check_vision.py`
→ `VISION` 则直接看图回答，不需要本 skill；`NO_VISION_SILENT` 用本 skill（DeepSeek 即此类）；
`NO_VISION_HARD` 图会让整轮 400，粘贴的图救不了，只能走文件路径。

## 操作步骤

1. 用户消息里有图（路径或粘贴），确认模型无视觉（上一步）。
2. 图片是文件路径：
   ```bash
   uv run --quiet --no-project scripts/qwen_vision.py /path/to/image.png [更多路径...] \
     --prompt "<用户真正想问的问题，例如：这张截图里的报错是什么？逐字读出报错信息>"
   ```
   多张图一次传入（各图之间用 `图1：` `图2：` 分隔说明）。
3. 图片是粘贴的：若 hook 已装，模型输入里已有 `【claude-qwen-vision】…` 注入文本，
   把它当作图片真实内容直接回答；没装 hook 就让用户提供文件路径。
4. 把 qwen 输出的文本当作图片的真实内容来回答用户的问题——**不要再说「我看不到图片」**。
   回答里引用图的内容时，说明是「根据图片内容」即可。

## 脚本（skills/claude-qwen-vision/scripts/）

| 脚本 | 作用 | 用法 |
|---|---|---|
| `qwen_vision.py` | 图片 → qwen3.8-max → 文本 | `uv run --quiet --no-project scripts/qwen_vision.py <路径> [--prompt …] [--base64 …] [--account paygo]` |
| `check_vision.py` | 判定模型视觉能力（快速路径 + 探测缓存） | `uv run --quiet --no-project scripts/check_vision.py [--profile 名] [--refresh]` |
| `user_prompt_hook.py` | UserPromptSubmit hook：粘贴的图自动转文本注入 | 由 install-hook.sh 接入，无需手动跑 |
| `install-hook.sh` | 把 hook 合并进 settings.json（会改配置文件） | `bash scripts/install-hook.sh [--config-dir DIR]`，运行前向用户说明 |

hook 装好后，**粘贴图片完全自动**：检测 `[Image #N]` 标记 → 模型无视觉才动作 →
取图（image-cache 优先，transcript 轮询兜底）→ qwen 描述 → `additionalContext` 注入。
任何失败都静默放行，绝不 block 用户消息。

## 已知限制

- **NO_VISION_HARD**（图直接 400 的端点）：粘贴的图整轮失败，hook 注入也救不了；只能走文件路径。
- `image-cache/` 是未文档化路径，hook 取不到时自动降级读 transcript（文档化，最多轮询 4s）。
- `CLAUDE_CONFIG_DIR` 指向别处（如 `~/.csk`）的会话：skill 和 hook 都读不到，要分别装
  （symlink skills 目录 + 对该目录重跑 install-hook.sh）。
- 凭证一律运行时从 mytokens 读取，脚本里不存任何 token。
