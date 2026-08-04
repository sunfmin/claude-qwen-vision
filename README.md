# claude-qwen-vision

给看不到图片的会话模型补上视觉。DeepSeek 等模型不支持图片时，用 mytokens 里的
qwen3.8-max（阿里云百炼 Anthropic 兼容端点）把图片转成文本，模型基于文本继续回答。

Skill 本体在 `skills/claude-qwen-vision/`（`SKILL.md` + 4 个脚本）：

| 脚本 | 作用 |
|---|---|
| `qwen_vision.py` | 图片（路径或 base64）→ qwen3.8-max → 文本描述 |
| `check_vision.py` | 判定当前模型是否支持图片（环境变量快速路径 + 探测缓存） |
| `user_prompt_hook.py` | UserPromptSubmit hook：粘贴的图自动转文本注入会话 |
| `install-hook.sh` | 把 hook 合并进 settings.json（幂等，改前备份） |

## 安装

```sh
npx skills add sunfmin/claude-qwen-vision -g -y    # 安装 skill
bash ~/.claude/skills/claude-qwen-vision/scripts/install-hook.sh   # 可选：粘贴的图全自动
```

前置：`mytokens` CLI + `qwen` profile（`ANTHROPIC_BASE_URL/MODEL/AUTH_TOKEN`），`uv`。

## 用法

`qwen_vision.py` 是**自包含**脚本（PEP 723 内嵌元数据，零第三方依赖），从任意 cwd 直接执行，
不需要 cd 进脚本目录：

```sh
uv run --no-project ~/.claude/skills/claude-qwen-vision/scripts/qwen_vision.py \
  /path/to/image.png [更多路径...] --prompt "让 qwen 看图的指令"
```

**输出保证**：成功时 stdout 必有内容；qwen 返回空文本 / 响应被截断（`max_tokens=8192` 上限告警）/
文件或网络出错，一律向 stderr 报错并以非零码退出，绝不静默输出空行。`--account paygo` 切按量付费。

## 限制

- 端点直接 400（NO_VISION_HARD）的模型：粘贴的图整轮失败，hook 救不了，只能走文件路径。
- `CLAUDE_CONFIG_DIR` 指向别处的会话（如 `~/.csk`）：skill 和 hook 需分别安装。
