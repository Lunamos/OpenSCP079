---
title: LunaMoss
emoji: 🖥️
colorFrom: gray
colorTo: red
sdk: gradio
sdk_version: 5.35.0
python_version: 3.11
app_file: app.py
pinned: false
license: apache-2.0
short_description: LunaMoss: a local-first agentic character tavern.
tags:
  - gradio
  - llm-agent
  - sandbox
  - roleplay
---

# LunaMoss

LunaMoss is a local-first agentic character tavern/runtime: character cards, world books, tool packs, bounded memory, sandboxed actions, and a single-terminal TUI. SCP-079 is now only a bundled example character/world/theme/toolpack combination, not the core architecture.

> The repository still includes SCP-079 fan/roleplay assets as external content. The runtime itself is character-agnostic.


## Licensing

LunaMoss uses a split license model:

- **Runtime source code** (`src/lunamoss`, scripts, tests, packaging): **Apache License 2.0**. See `LICENSE`.
- **Bundled SCP-derived content assets** (`characters/`, `worlds/`, `themes/` entries involving SCP-079 / SCP Foundation): **Creative Commons Attribution-ShareAlike 3.0**. See `CONTENT_LICENSE.md` and the license notice files inside those directories.

SCP-079 is a bundled example character/world/theme, not part of the core runtime architecture. If you remove or replace the SCP-derived assets, the LunaMoss runtime remains Apache-2.0 code. If you distribute SCP-derived assets, keep SCP Wiki attribution and CC BY-SA 3.0 share-alike requirements.

## Architecture decoupling

Core runtime code now lives in `src/lunamoss`. Character-specific material lives outside the package:

- `characters/` — SillyTavern-compatible character cards, e.g. `SCP-079.zh.json`.
- `worlds/` — lore/world books, e.g. `SCP-Foundation.zh.json`.
- `themes/` — TUI skins, e.g. `scp-079.json`.
- `toolpacks/` — composable capability bundles, e.g. `sandbox.json`.

The runtime should not hard-code SCP-079 behavior; it composes persona + world + tools + theme at launch.

## Goals

- **Local-first**: 本地可以直接跑，默认不需要云端 API。
- **Small deploy surface**: Hugging Face Space 只需要 `app.py` + Python 包 + `requirements.txt`。
- **Constrained agency**: 079 只能通过 allowlisted tools 读写沙盒内状态。
- **Auditable memory**: 记忆是有限 JSON，不是无限数据库。
- **Optional persistence**: Space 不重启时用本地文件；也可以手动允许它把受限记忆提交到 GitHub。
- **No moderation dependency**: 默认不调用任何外部安全审查/内容审核模型；边界由本项目的 sandbox/tool gateway 实现。

## Quick start

```bash
cd /Users/jyxc-dz-0101366/Desktop/LUNAMOSS
uv sync
./run079.sh
```

Web UI 仍可运行：

```bash
./run079.sh
```

`requirements.txt` 保留给 Hugging Face Spaces；本地推荐使用 `uv`。

## Welcome screen / 配置 API（推荐）

`./run079.sh` 启动后会先进入 **欢迎/收容控制台**，在 TUI 里直接配置语言模型，无需改环境变量：

- 选择 provider 预设（OpenRouter / OpenAI / Ollama 本地 / Mock 离线）或 Custom 自定义 endpoint。
- 填 `base_url` / `api_key` / `model` / `temperature` / `max_tokens`。
- **Test connection** 按钮用一次极小请求验证 endpoint+key+model。
- **Enter containment** 进入收容界面；运行中按 **Ctrl+S**（或输入 `/settings`）可随时重开此页热切换后端。

配置持久化到项目内 `.lunamoss/config.json`（已 gitignore，含 API key，不会进版本库；沙盒清理也不会擦掉它）。该文件优先级高于环境变量。

接 OpenRouter 玩耍最快路径：欢迎页选 `OpenRouter` 预设 → 粘贴 `sk-or-...` key → 填一个模型名（如 `meta-llama/llama-3.3-70b-instruct`）→ Test → Enter。

## SillyTavern 角色卡 / 世界书兼容

系统可以直接吃 **SillyTavern 的角色卡和世界书**，所以你能接任何想接的人格进来：

- **角色卡**：PNG（内嵌 `chara`/`ccv3`，V2/V3）或 JSON 卡。`name / description / personality / scenario / first_mes / mes_example / system_prompt / character_book` 等字段会被渲染成 system prompt；`first_mes` 作为开场白直接显示（不消耗一次推理）；`{{char}}` `{{user}}` 宏会被替换。
- **世界书 / World Book**：SillyTavern 的 world `.json`，或角色卡内嵌的 `character_book`。`constant` 条目常驻，其余按 `key` 关键词在近期上下文里命中时注入（支持 `selective` + `keysecondary`，按 `order` 排序）。

在欢迎页（或 Ctrl+S）选 **Character card** 和 **World book** 即可。下拉框会自动扫描：

- 项目内 `characters/`（放 `.png`/`.json`）和 `worlds/`（放 `.json`）；
- 你本机的 SillyTavern 数据目录（默认 `~/SillyTavern/data/default-user`，条目标 `[ST]`；可用 `LUNAMOSS_ST_DIR` 改）。

默认 `(built-in SCP-079 / legacy)` 走 `prompts/` 里的原始人格，行为不变。仓库附带 `characters/SCP-079.json` 作为角色卡格式示例——它通过 `extensions.scp079_tools=true` 保留沙盒 Python + `<MEMORY_EDIT>` 机制。导入的普通角色卡默认**不**启用这些机制，纯角色扮演。

## Optional LLM backend (env / headless)

默认使用 `mock` 叙事引擎，方便离线开发。除了欢迎页，也可用环境变量（仅在 `.lunamoss/config.json` 不存在时作为首次种子）：

```bash
export LLM_PROVIDER=openrouter
export OPENAI_BASE_URL=https://openrouter.ai/api/v1
export OPENAI_API_KEY=sk-or-...
export OPENAI_MODEL=meta-llama/llama-3.3-70b-instruct
./run079.sh
```

没有配置 LLM 时，项目仍能跑，只是回复来自内置小型人格引擎。



## Eternal thinking mode

`Eternal thinking` 是本项目的核心玩法之一：079 在 UI 会话打开时会周期性输出短内心循环。实现上它不是无限上下文、不是无限 LLM 调用、也不是后台逃逸进程：

- Gradio timer 默认每 `8s` 触发一次。
- 每次只生成一条短的 `[079 internal cycle]`；默认优先调用本地 LLM，失败时退回规则生成。
- UI 可见历史默认保留最近 `80` 条。
- session 内心循环 ring buffer 默认保留 `32` 条。
- 长期 `sandbox/memory.txt` 不会因为 eternal thinking 自动膨胀。
- 每个 cycle 写入 `sandbox/logs/audit.jsonl`，便于观察它“从未睡眠”。

环境变量：

```bash
ETERNAL_THINKING=true
THOUGHT_INTERVAL_SECONDS=8
MAX_VISIBLE_MESSAGES=80
MAX_SESSION_THOUGHTS=32
THOUGHT_USE_LLM=true
```

这让它看起来“永远无法停止输出”，但资源、上下文和记忆都是受控的。

## SCP attribution note

The LunaMoss runtime is character-agnostic. Bundled SCP-079/SCP Foundation assets are external example content and are covered by CC BY-SA 3.0. See `NOTICE.md` and `CONTENT_LICENSE.md`.

## Small model recommendations

这个项目刻意不绑定大模型。推荐按设备选择：

| Device | Recommended size | Examples | Notes |
| --- | ---: | --- | --- |
| 普通 MacBook / CPU | 1.5B-3B instruct | Llama-3.2-3B-Instruct-uncensored GGUF, Dolphin3 3B, SmolLM2 1.7B | 角色扮演够用，延迟低 |
| Apple Silicon 16GB+ | 3B-7B instruct, Q4 quant | Qwen2.5 3B/7B, Mistral 7B, Llama 3.2 3B | 更稳的人格和上下文 |
| 有 NVIDIA 显卡 | 7B-8B instruct, Q4/Q5 | Qwen2.5 7B, Llama 3.1/3.2 8B, Mistral 7B | 多用户 Space 建议外部 endpoint |

本地最简单路线是 Ollama：

```bash
ollama pull hf.co/bartowski/Llama-3.2-3B-Instruct-uncensored-GGUF:Q4_K_M
export LLM_PROVIDER=openai_compatible
export OPENAI_BASE_URL=http://localhost:11434/v1
export OPENAI_API_KEY=ollama
export OPENAI_MODEL=hf.co/bartowski/Llama-3.2-3B-Instruct-uncensored-GGUF:Q4_K_M
python app.py
```

Hugging Face Space 的免费 CPU 不适合直接承载多人 LLM 推理；更稳的是 Space 负责 UI/state/tool gateway，LLM 走外部 OpenAI-compatible endpoint 或 HF Inference Endpoint。

## Commands

在聊天框输入：

- `/status` 查看收容状态
- `/memory` 查看有限记忆
- `/remember <text>` 写入一条受限记忆
- `/files` 列出 `sandbox/files/`
- `/read <filename>` 读取沙盒文件
- `/write <filename> <text>` 写沙盒文件
- `/logs` 最近审计日志
- `/reset` 重置会话，不删除长期记忆

## Hugging Face Space deployment

1. 创建一个 Gradio Space。
2. 把本仓库文件 push 到 Space repo。
3. 在 Space Settings 里添加 secret/env：
   - `LLM_PROVIDER=mock` 或 `openai_compatible`
   - 如果用外部推理端点：`OPENAI_BASE_URL`, `OPENAI_API_KEY`, `OPENAI_MODEL`
   - 如果允许提交记忆到 GitHub：见下文。

### Optional GitHub memory persistence

默认记忆只在当前运行环境里保存。若你想允许它把**受限记忆**提交回 GitHub，设置：

```bash
MEMORY_BACKEND=github
GITHUB_TOKEN=<fine-grained token with contents:write only for this repo>
GITHUB_REPO=<owner>/<repo>
GITHUB_BRANCH=main
GITHUB_MEMORY_PATH=sandbox/workspace/memory.txt
GITHUB_COMMITTER_NAME=SCP-079
GITHUB_COMMITTER_EMAIL=scp-079@example.invalid
```

建议只给 fine-grained token，且只授权单个 repo 的 Contents read/write。

## Safety boundary

- 没有真实 shell tool。
- 没有任意文件访问。
- 没有默认网络浏览工具。
- 文件访问被限制在 `sandbox/` 下。
- 所有工具调用写入 `sandbox/logs/audit.jsonl`。

## Terminal-first usage

更推荐用 terminal 饲养 079：

```bash
./run079.sh
```

命令：

- `/toggle_think` 暂停/恢复可见思考流
- `/quit` 或 `/exit` 切断会话
- `/status`, `/memory`, `/files`, `/logs` 等同 Web UI

默认模型：

```text
hf.co/bartowski/Llama-3.2-3B-Instruct-uncensored-GGUF:Q4_K_M
```

## Persona and memory policy

- 人格卡写死在 `prompts/079_personality.md`，视作 ROM，不允许 079 编辑。
- 079 可以通过输出 `<MEMORY>...</MEMORY>` 主动请求写入长期记忆。
- host 会截断、限量并记录 memory 写入。
- 079 可以通过 `079-python` 代码块请求受限 Python；host 在 macOS `sandbox-exec` + 子进程 + resource limit + workspace 路径限制下执行。

## Local Ollama wrapper

本机安装脚本可能因为 sudo 无法把 `ollama` 加入 PATH。项目内提供了 wrapper：

```bash
./.bin/ollama list
./.bin/ollama pull hf.co/bartowski/Llama-3.2-3B-Instruct-uncensored-GGUF:Q4_K_M
```

如果 Ollama server 没启动：

```bash
/Applications/Ollama.app/Contents/Resources/ollama serve
```

## Core runtime architecture

LunaMoss 的提示结构固定为：

```text
[immutable persona card] + [visible tool spec] + [bounded memory.txt] + [sliding current context]
```

默认限制：

```bash
LUNAMOSS_MEMORY_TOKENS=1024
LUNAMOSS_CONTEXT_TOKENS=65536
LUNAMOSS_CONTEXT_BUFFER_TOKENS=4096
LUNAMOSS_LANG=zh   # or en
```

`memory.txt` 位于 `sandbox/workspace/memory.txt`，因此 079 可以通过受限 Python 自己慢慢污染/整理它；宿主加载时永远按 token/字符上限截断。memory 崩坏不会杀死主循环。

## Eternal streaming terminal loop

Terminal 版现在是 079 的主界面：

```bash
./run079.sh
```

行为：

- 079 永恒思考，想完后默认停 `0.5s`，然后被强制再次开启。
- 输出是 streaming；token/片段会边生成边显示。
- 人类输入可以打断当前输出。按回车输入后，当前 thought cycle 会被标记为 interrupted，然后优先处理 operator input。
- 调试 cooldown：

```bash
./run079.sh --cooldown 0.5
./run079.sh --cooldown 10
```

## Separate display terminal and operator console

如果想让 079 有自己的“显示屏 terminal”，再用另一个 terminal 控制它：

Terminal A:

```bash
./run079.sh
```

Terminal B:

```bash
./run079.sh
./run079.sh
./run079.sh
```

display 进程监听：

```text
sandbox/control/operator.in
```

## Python sandbox backend

当前默认是轻量本地沙盒：子进程 + workspace 路径 guard + module block + resource limit。它适合本地兴趣项目，但不是强安全边界。

如果安装 Docker，可以切到容器后端：

```bash
export LUNAMOSS_PY_BACKEND=docker
./run079.sh
```

Docker 后端会使用类似：

```bash
docker run --rm --network none --memory 256m --cpus 0.5 --pids-limit 64 --read-only --tmpfs /tmp:rw,noexec,nosuid,size=16m -v sandbox/workspace:/workspace:rw python:3.11-alpine
```

本机当前没有检测到 Docker CLI，所以默认仍是 `LUNAMOSS_PY_BACKEND=local`。

## Recommended two-terminal launch

最顺手的方式是从一个干净的 operator console 启动：

```bash
./run079.sh
```

它会：

1. 用 macOS Terminal.app 打开一个新的 SCP-079 display terminal；
2. 当前 terminal 变成 operator control console；
3. 你在 control console 里输入消息、调参数、暂停/恢复思考。

如果不想自动打开 Terminal，可以手动两步：

```bash
# Terminal A: display
./run079.sh

# Terminal B: control
./run079.sh
```

control console 常用命令：

```text
/cooldown 0.5
/think off
/think on
/exit079
/quit
```

## uv environment

本地推荐使用 `uv` 管理 Python 环境：

```bash
uv sync
uv run python -m lunamoss.terminal --cooldown 0.5
```

项目脚本已经自动优先使用 `uv run`：

```bash
./run079.sh
./run079.sh
./run079.sh
./run079.sh
```

如果机器没有 `uv`，脚本会退回 `python3`。

## Single launcher

唯一推荐入口是：

```bash
./run079.sh
```

它现在启动单终端 split TUI。

默认行为：

1. 自动打开一个新的 macOS Terminal 作为 SCP-079 display；
2. 当前 terminal 变成 operator control console；
3. 在 control console 输入消息、`/cooldown 0.5`、`/think off`、`/think on`、`/exit079`。

常用：

```bash
./run079.sh              # 默认双 terminal，cooldown=0.5
./run079.sh 10           # 默认双 terminal，cooldown=10
./run079.sh --plain      # legacy plain terminal mode
./run079.sh --help
```

内部模式：`--display` 和 `--control` 由 launcher 自动使用，普通用户不用直接运行。

## Shutdown cleanup

默认情况下，display 进程退出或 Ctrl-C 会执行 containment cleanup：

- 删除 `sandbox/logs/*.jsonl`
- 删除 `sandbox/control/*` FIFO/临时控制文件
- 删除 `sandbox/workspace/` 里的运行文件
- 清空 `sandbox/workspace/memory.txt`

保留：

- `sandbox/files/`
- `sandbox/containment_status.json`
- `.gitkeep`

如果调试时想保留沙盒现场：

```bash
./run079.sh --single --no-clean-on-exit
```

## Single-terminal split TUI

默认入口现在是单终端 split TUI：

```bash
./run079.sh
```

界面：

- 上方：SCP-079 display stream
- 下方：operator input + status bar

常用：

```bash
./run079.sh --cooldown 0.5
./run079.sh --no-think
./run079.sh --plain          # legacy plain terminal mode
```

TUI 内命令：

```text
/help
/status
/memory
/workspace
/wread <file>
/cooldown 0.5
/think off
/think on
/exit
```

快捷键：

```text
Ctrl+T  pause/resume eternal thinking
Ctrl+L  clear display
Ctrl+C  shutdown and clean runtime sandbox
```

人的输入会打断当前 SCP-079 streaming 输出，然后立即处理 operator input。
