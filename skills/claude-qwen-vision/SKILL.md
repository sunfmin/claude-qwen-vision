---
name: claude-qwen-vision
description: >
  Handles images when the session model is blind to them (e.g. DeepSeek): the user's message
  contains an image — pasted into the terminal (the [Image #N] placeholder) or an image file
  path — convert it to text with qwen3.8-max via scripts/qwen_vision.py and answer from that
  text instead of trying to view the image directly. Triggers — 用户贴图/截图/paste an image,
  「看下这张图」「读出图里的文字」「图片在 xxx.png」. If user_prompt_hook is installed,
  pasted images arrive already described — skip.
---

# claude-qwen-vision — 给盲模型补上视觉

会话模型看不到图片（**盲**，如 DeepSeek）时，用 mytokens 里的 qwen3.8-max 把图片转成
文本，模型基于文本继续回答——相当于给模型补上一只眼睛。

## 分支：图从哪来

| 来源 | 处理 |
|---|---|
| prompt 里的图片路径（「图片在 /path/x.png」） | 直接跑 `qwen_vision.py` 转文本 |
| 粘贴进终端的图（`[Image #N]`） | hook 已装 → 描述已注入（`【claude-qwen-vision】…`），直接用；未装 → 请用户把图存成文件给路径 |
| 拿不准模型是否盲 | `check_vision.py` 判定：VISION → 能看图，无需本 skill；NO_VISION_SILENT → 盲，用本 skill；NO_VISION_HARD → 图会让整轮失败，粘贴的图救不了，只能走路径 |

## 步骤

1. 确认用户消息里有图，且模型是盲的（上面分支表）。
2. 跑脚本把图转成文本——**脚本是自包含的，从任意 cwd 都能跑，不需要 cd 进脚本目录**：

   ```bash
   uv run --no-project ~/.claude/skills/claude-qwen-vision/scripts/qwen_vision.py \
     /path/to/image.png [更多路径...] \
     --prompt "<用户真正想问的问题，例如：这张截图里的报错是什么？逐字读出报错信息>"
   ```

   多张图一次传入，输出按 `图1：` `图2：` 分段。

   **输出保证**：成功时 stdout 一定有内容；qwen 返回空文本、响应被截断、文件或网络出错，脚本都
   向 stderr 报错并以非零码退出——不会静默输出空行。遇到「没内容」的返回请按 stderr 的提示重试。
3. 以 qwen 的文本输出为图片的真实内容，直接、完整地回答用户的问题。

**完成标准**：回答建立在 qwen 的文本输出之上（不再有「看不到图」这类话），用户的问题
被完整回答。

## 脚本（skills/claude-qwen-vision/scripts/）

| 脚本 | 作用 |
|---|---|
| `qwen_vision.py` | 图片（路径或 --base64）→ qwen3.8-max → 文本；`--account paygo` 切换账号 |
| `check_vision.py` | 判定模型是否盲（已知模型走环境变量快速路径，未知模型探测一次并缓存） |
| `user_prompt_hook.py` | UserPromptSubmit hook：粘贴的图自动转文本注入（内部机制见脚本 docstring） |
| `install-hook.sh` | 把 hook 合并进 settings.json（幂等，改前备份） |

## 限制

- NO_VISION_HARD 的模型：粘贴的图会让整轮 400 失败，只能走文件路径。
- `CLAUDE_CONFIG_DIR` 指向别处（如 `~/.csk`）的会话：skill 和 hook 要分别装。
- 凭证一律运行时从 mytokens 读取，脚本里不存任何 token。
