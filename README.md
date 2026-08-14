# claude-qwen-vision

给看不到图片的会话模型补上视觉。DeepSeek 等模型不支持图片时，用 mytokens 里的
qwen3.8-max（阿里云百炼 Anthropic 兼容端点）把图片转成文本，模型基于文本继续回答。
在线服务不可用（额度耗尽、断网、没配 mytokens）时自动回退到本地 Qwen3-VL（MLX，
模型在 HuggingFace cache 里，离线可用）。

Skill 本体在 `skills/claude-qwen-vision/`（`SKILL.md` + 5 个脚本）：

| 脚本 | 作用 |
|---|---|
| `qwen_vision.py` | 图片（路径或 base64）→ qwen3.8-max → 文本描述；在线不可用自动回退本地模型 |
| `qwen_vision_local.py` | 离线回退：本地 Qwen3-VL（MLX，从 HF cache 直接加载，不发网络请求） |
| `check_vision.py` | 判定当前模型是否支持图片（环境变量快速路径 + 探测缓存） |
| `user_prompt_hook.py` | UserPromptSubmit hook：粘贴的图自动转文本注入会话 |
| `install-hook.sh` | 把 hook 合并进 settings.json（幂等，改前备份） |

## 安装

```sh
npx skills add sunfmin/claude-qwen-vision -g -y    # 安装 skill
bash ~/.claude/skills/claude-qwen-vision/scripts/install-hook.sh   # 可选：粘贴的图全自动
```

前置：`mytokens` CLI + `qwen` profile（`ANTHROPIC_BASE_URL/MODEL/AUTH_TOKEN`），`uv`。
本地回退另需：HF cache 里有 Qwen3-VL（见下），首次运行由 `uv run` 装 mlx-vlm（已在 uv 缓存）。

## 用法

`qwen_vision.py` 是**自包含**脚本（PEP 723 内嵌元数据，零第三方依赖），从任意 cwd 直接执行，
不需要 cd 进脚本目录：

```sh
uv run --no-project ~/.claude/skills/claude-qwen-vision/scripts/qwen_vision.py \
  /path/to/image.png [更多路径...] --prompt "让 qwen 看图的指令"
```

**输出保证**：成功时 stdout 必有内容；qwen 返回空文本 / 响应被截断（`max_tokens` 上限告警）/
文件或网络出错，一律向 stderr 报错并以非零码退出，绝不静默输出空行。`--account paygo` 切按量付费。

**输出上限**：默认 `--max-tokens 131072`，可用 `--max-tokens N` 继续放大（该参数 API 端
必填、实测接受 ≥524288；只是上限，实际按生成量计费）。请求中显式关掉 thinking——
token-plan 网关上 qwen3.8-max 的 thinking 无上界，会吃光整个输出预算
（实测 8192 全被 thinking 占掉、text 一个 token 都不剩）。

## 本地回退

在线失败（mytokens 缺失、凭证失败、网络错误、空响应、429 额度耗尽）时，
`qwen_vision.py` 自动改跑同目录的 `qwen_vision_local.py`：stderr 打一行 `改用本地模型`，
stdout 保持只有图片描述，调用方无需区分。本地脚本用 HF cache 里的 MLX 版 Qwen3-VL
（`~/.cache/huggingface/hub/`），全程不发网络请求：

| `--local-model` | repo | 备注 |
|---|---|---|
| `30b`（默认） | mlx-community/Qwen3-VL-30B-A3B-Instruct-4bit | 质量最好；M4 Pro 实测加载 ~5s、整轮 ~10s |
| `8b` | mlx-community/Qwen3-VL-8B-Instruct-8bit | 加载更快、更省内存 |

指定模型在 cache 缺失时自动退到另一个；两个都没有则明确报错并列出 repo。
`--no-local-fallback` 关闭回退（在线失败直接非零退出）。

## 限制

- 端点直接 400（NO_VISION_HARD）的模型：粘贴的图整轮失败，hook 救不了，只能走文件路径。
- `CLAUDE_CONFIG_DIR` 指向别处的会话（如 `~/.csk`）：skill 和 hook 需分别安装。
