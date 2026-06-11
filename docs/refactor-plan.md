# LunaMoth 重构方案（草案，待 owner 审定）

> 目标：① 更清晰的代码库 ② 组件解耦、便于多 agent 协作维护 ③ 完整日志系统
> ④ 前后端彻底分离（TUI/CLI 与后端逻辑独立演进，为桌面端/网页端铺路）
> ⑤ 前瞻：插件 / 角色卡市场。
> 参考优先级：Claude Code ≈ hermes-agent > AstrBot > SillyTavern > cc-switch。
> 本文只是方案，未做任何代码改动。

---

## 1. 现状诊断 — 每个目标卡在哪

### 1.1 代码库清晰度

- `src/lunamoth/` 根目录平铺 **30 个模块**（唯一的子包是 `presence/`），层次靠命名约定，
  违反我们自己定下的"新功能进子包"规约（presence/ 是孤例）。
- `tui.py` 1534 行单体 ≈ 全项目 22%：布局、流式渲染、命令解析、权限交互、面板视图、
  设置变更全在一个文件里。这正是双 agent 冲突最频繁的文件。
- 职责混居：`cli.py`（471 行）同时管 CLI 入口、daemon 启停、session 环境激活；
  `agent.py`（627 行）同时管系统提示词拼装、工具执行、presence、transcript 接线。

### 1.2 耦合度（最严重的问题）

- **TUI 直接访问 agent 的 ~20 个属性**（实测 grep）：`agent.state / memory / presence /
  goals / tools / llm / audit / sandbox / settings / char_name / context_limit / _command …`
  后端任何内部结构调整都会波及 tui.py；terminal.py 又重复一遍同样的伸手。
- **带内控制字符协议**：流式输出用 `\x01/\x02`（dim）`\x03/\x04`（think）混在文本里，
  每个前端各自解析、各自小心 `strip_dim()`。这是字符串化的私有协议——
  无法序列化上网络，新增一种"事件"（如工具进度）就要发明新控制符。
- 命令（/mode /reasoning /goal…）在 tui.py 和 terminal.py 各实现一份，已经出现行为漂移。

### 1.3 日志

- 现状只有两样：`audit.jsonl`（工具调用安全审计）和 `transcript.db`（对话记录）。
- **整个代码库没有一行 `logging` 调用**。LLM 请求失败的细节、MCP 子进程死掉的原因、
  sandbox 拒绝写入的路径——要么闪过屏幕，要么彻底消失。用户无从检查，开发者无从 debug。

### 1.4 前后端分离

- 没有任何协议层。TUI 是后端对象的直接消费者（同进程、同对象图）。
  桌面端/网页端按现状只能再写一个"伸手 20 个属性"的客户端。
- roadmap 里的 remote gateway / web UI 全部被这一层缺失阻塞。

### 1.5 插件 / 市场

- 内容侧其实已经是"数据即插件"：`characters/ worlds/ toolpacks/ skills/ themes/`
  全是声明式目录，离打包/分发只差一个清单格式和安装命令。
- 代码侧没有任何扩展点：新工具 = 改 `tools.py`（416 行 if/elif 调度），
  没有注册表、没有 hook、没有第三方代码加载机制。

---

## 2. 参考项目各取什么（侦察结论）

### hermes-agent（最重要，MIT 可直接抄）

- **类型化事件流**（`gateway/stream_events.py`）：7 个 frozen dataclass —
  `MessageChunk / MessageStop / Commentary / ToolCallChunk / ToolCallFinished /
  LongToolHint / GatewayNotice`。agent 循环只产事件，**渲染是 adapter 的事**
  （`render_message_event` / `format_tool_event` 钩子）。同一条事件流喂 stdio TUI、
  喂 Telegram、喂 SSE/WebSocket——这是前后端分离的全部秘密。
- **dispatcher 永不向 agent 线程抛异常**（`stream_dispatch.py`）：前端崩溃不拖死后端。
- **日志**（`hermes_logging.py`）：stdlib logging；`~/.hermes/logs/` 下
  `agent.log`(INFO+) / `errors.log`(WARNING+) / `gateway.log` / `gui.log` 按组件分流
  （logger 前缀 → 文件的 `COMPONENT_PREFIXES` 表）；record factory 自动注入
  `[session_id]`（threading.local）；`_RedactingFormatter` 抹掉密钥。
- **工具注册表**（`tools/registry.py`）：无装饰器魔法，模块顶层显式
  `registry.register(name, toolset, schema, handler, check_fn, ...)`；
  check_fn 带 30s TTL 缓存（探测 docker 之类不必每回合做）。
- **插件**（`hermes_cli/plugins.py`）：四来源（bundled / ~/.hermes/plugins / 项目 .hermes/plugins /
  pip entry-points），`plugin.yaml` + `register(ctx)`；hook 点：
  `pre/post_tool_call, transform_tool_result, pre/post_llm_call,
  pre/post_approval_request, on_session_start/end`；`ctx.llm` 提供宿主代管的 LLM
  门面（插件不持有 key）。
- **权限审批跨进程**：contextvars 绑 session key，审批请求作为异步事件送达前端，
  回复走同一通道——正是我们 request_permission 远程化要走的路。

### Claude Code（设计哲学最重要）

- **插件 = 大部分是内容，不是代码**：一个插件目录可装 commands(markdown) /
  agents(markdown) / skills(markdown) / hooks(配置+shell) / MCP servers(json 配置)，
  清单 `.claude-plugin/plugin.json`。**市场 = 一个 git 仓库 + `marketplace.json` 索引，
  安装 = clone**。零服务器、零审核流水线，对我们体量刚好。
- **headless 协议先行**：`claude -p --output-format stream-json` 把内部事件流直接以
  JSONL 吐到 stdout——"协议即产品"，TUI 只是协议的一个客户端。我们可以用极低成本
  先做 `lunamoth run -p` 验证事件流设计。
- **hooks**：在 PreToolUse/PostToolUse/Stop 等生命周期点跑用户 shell 命令，
  是"完整插件系统"之前最便宜的扩展点。
- 会话即 JSONL 文件、`--debug` 开诊断日志：日志/可观测性是一等公民。

### AstrBot（取长避短）

- 取：插件 `metadata.yaml` + 可选 `requirements.txt`（装载时 pip 预检）+
  `_conf_schema.json`（配置 schema 驱动 UI）；**LogBroker 环形缓冲**
  （deque(maxlen=500) + SSE `/api/live-log`）——网页端看日志就靠它；
  市场 = dashboard 拉一个在线索引，安装 = git clone 进 `data/plugins/`。
- 避：**Quart dashboard 与核心同进程共享对象图**，路由直接调
  `plugin_manager.reload()`、直写配置文件——没有协议边界，核心改字段 dashboard 必须
  同步改，无法分机部署。这正是我们要靠协议层避免的反面教材。

### SillyTavern / cc-switch

- ST：内容兼容面不动（卡/世界书/正则脚本是市场的"商品"格式）；
- cc-switch：roster/会话切换的 UX 已吸收，本次重构不再新取。

---

## 3. 目标架构

### 3.1 包布局（src/lunamoth/）

```
src/lunamoth/
├── core/                # 纯后端：不 import 任何前端/Textual
│   ├── agent.py         # 编排循环（瘦身后）
│   ├── prompt.py        # 系统提示词拼装（从 agent.py 拆出）
│   ├── llm.py           # 流式客户端 + agent loop
│   ├── context.py       # ContextBuffer
│   ├── compaction.py    # （邻居负责，搬移时只动路径）
│   ├── transcript.py
│   ├── providers.py
│   └── state.py         # EnvState
├── content/             # SillyTavern 兼容层（纯数据加载，无运行时依赖）
│   ├── cards.py  worldinfo.py  persona.py  rules.py  themes.py
├── tools/               # 工具域
│   ├── gateway.py       # ToolGateway（从 tools.py 改名搬入）
│   ├── registry.py      # 【新】hermes 式声明注册表
│   ├── builtin/         # 内置工具按文件拆（terminal.py files.py goals.py …）
│   ├── runner.py  sandbox.py  mcp.py  skills.py  goals.py  memory.py
├── protocol/            # 【新·契约层】整个重构的心脏
│   ├── events.py        # 类型化事件（frozen dataclass，零依赖）
│   ├── api.py           # CharaHandle：前端唯一允许触碰的后端门面
│   ├── commands.py      # /命令 注册表（TUI/terminal/web 共用一份实现）
│   └── codec.py         # 事件/命令 ↔ JSON（wire 格式，版本字段）
├── server/              # 【新·后做】JSON-RPC over stdio + WebSocket
│   ├── dispatch.py  stdio.py  ws.py
├── obs/                 # 【新】可观测性
│   ├── log.py           # logging 设施（见 §5）
│   ├── audit.py         # 现 audit.py 搬入，职责不变
│   └── broker.py        # LogBroker 环形缓冲（AstrBot 式，供面板/网页）
├── session/             # 会话与配置域
│   ├── sessions.py  settings.py  config.py  cleanup.py
├── presence/            # 不动（已是子包）
├── front/               # 前端域：唯一允许 import textual 的地方
│   ├── tui/             # tui.py 拆分：app.py / stream_view.py / spotlight.py / commands.py
│   ├── terminal.py  roster.py  wizard.py  art.py
│   └── cli.py           # 入口 + daemon 管理
└── plugins/             # 【新·最后做】manager.py  hooks.py  market.py
```

### 3.2 依赖方向（用测试强制）

```
front/  ──→  protocol/  ──→  core/ + tools/ + session/ + content/
server/ ──→  protocol/
plugins/ ──→ protocol/ + tools.registry
obs/ ←── 所有人（只出不进）
```

铁律（写成 `tests/test_architecture.py`，AST 扫 import，违规即红）：

1. `core/ tools/ content/ session/` 禁止 import `front/ server/`，禁止 import textual。
2. `front/` 只许 import `protocol/`（+obs），**不许直接 import core**。
   ——"TUI 伸手 20 个属性"从机制上变为不可能。
3. `protocol/events.py` 零项目内依赖（纯 dataclass），保证可独立序列化。

### 3.3 三种记录，职责互斥（保持现状定义，写进文档）

| 介质 | 是什么 | 给谁看 |
|---|---|---|
| `transcript.db` | 对话本身（恢复用，史实） | chara 与用户 |
| `audit.jsonl` | 工具调用安全审计（谁、何时、动了什么） | 用户安全检查 |
| `logs/*.log` | 【新】运行诊断（错误、重试、时延、子进程） | 用户排障 + 开发者 |

---

## 4. 协议层设计（目标②④的共同答案）

### 4.1 事件（hermes 词汇表 + 我们的需要）

```python
# protocol/events.py — 全部 frozen dataclass，零依赖
TextDelta(text, channel)             # 正文增量；channel='say'(对用户说)|'muse'(自语/过自己的生活)，见 §9
ThinkDelta(text)                     # 推理增量（取代 \x03/\x04 THINK 通道）
ToolStart(name, preview, index)      # 取代 \x01/\x02 dim 通道的工具部分
ToolEnd(name, ok, duration, index)
Notice(kind, text)                   # 重试提示 ⚠ retry n/5、presence 事件、截断续写提示
PermissionAsk(id, action, timeout)   # request_permission 出站（回复走 CharaHandle）
TurnEnd(reason)                      # 'done' | 'interrupted' | 'error'
Error(kind, message)                 # 失败公开示人（符合无 fallback 铁律）
StateChanged(snapshot)               # 遥测面板订阅（net/goals/memory 等聚合快照）
```

要点：

- **dim/think 的"怎么显示"归前端**：TUI 渲染灰色、plain 终端打 ANSI dim、
  网页端折叠成 ✶ 指示器——后端只说"这是 think"，不再发控制字符。
  `strip_dim()` 这类易错清洗随之消亡（上下文提交的就是干净文本）。
- 事件天然可 JSON 化（codec.py），`lunamoth run -p --stream-json` 一行一个事件
  ——Claude Code headless 模式同款，也是 server/ 阶段的 wire 格式预演。
- dispatcher 学 hermes：**事件投递永不向 agent 线程抛异常**。

### 4.2 门面（CharaHandle）

```python
# protocol/api.py — 前端世界里"后端"只有这一个名字
class CharaHandle:
    def send(text) -> None              # 用户说话（异步，事件流里回结果）
    def interrupt() -> None
    def command(name, args) -> Reply    # /mode /reasoning /goal… 统一入口
    def reply_permission(id, granted)
    def snapshot() -> StateSnapshot     # 遥测面板一次性拉取（dataclass，非裸对象）
    def subscribe(callback)             # 事件订阅（进程内=回调；跨进程=流）
```

- `protocol/commands.py` 一份命令注册表：名称、参数 schema、help 文本、处理函数。
  TUI/terminal/未来 web 的 /help 与行为自动一致，消灭现在的双份实现。
- 同进程时 CharaHandle 直接包住 LunaMothAgent；跨进程时换成 RPC stub——
  **前端代码一行不改**。这就是 hermes "web/desktop 都只是 dispatch 的客户端" 的做法。

### 4.3 传输（server/，后做）

- 帧格式：newline-delimited JSON-RPC（hermes `tui_gateway.dispatch` 同款），
  方法 = CharaHandle 的方法，事件 = server push。带 `protocol_version` 字段。
- 两个 transport 共用一个 dispatch：stdio（`lunamoth serve --stdio`，桌面壳用）
  和 WebSocket（`/api/ws`，远程 TUI / 网页用，token 鉴权）。
- 一个 serve 进程托管多个 chara（roster 即服务端目录），对齐 roadmap 的
  remote gateway 目标。

---

## 5. 日志系统设计（目标③）

零新依赖，stdlib logging（hermes 路线；AstrBot 的 loguru 不值得为此破戒）：

- **`obs/log.py`**：`setup_logging(level, session=None)`。
  - 文件：`~/.lunamoth/logs/lunamoth.log`（INFO+，RotatingFileHandler 5MB×3）、
    `errors.log`（WARNING+）。组件前缀分流表学 hermes：`lunamoth.core.llm` /
    `lunamoth.tools` / `lunamoth.front` / `lunamoth.server`。
  - **会话注入**：record factory 自动加 `[chara名]`（threading.local），
    多 chara 的 daemon 日志可分辨；可选 `sessions/<name>/logs/` 每会话独立文件。
  - **脱敏 Formatter**：API key / Bearer token 模式直接抹除（hermes `_RedactingFormatter`）。
- **打点最低标准**（重构时顺手补，不必专项）：每次 LLM 请求（模型、token 数、时延、
  finish_reason）、每次重试与原因、工具执行（名称、时长、ok）、MCP 子进程生死、
  sandbox 拒绝、compaction 触发、daemon 启停。
- **`--debug` / `LUNAMOTH_DEBUG=1`**：DEBUG 级 + LLM 请求体落盘（脱敏后），
  对应 Claude Code `--debug`。`lunamoth doctor` 顺手打印 logs 路径和最近错误。
- **LogBroker**（obs/broker.py）：deque(maxlen=500) 内存环 + 订阅队列。
  近期收益：spotlight 面板加 "log" 视图（/panel log）；远期收益：网页端
  `/api/live-log` SSE 直接复用（AstrBot 验证过的模式）。
- audit.jsonl 不动——它是给用户看的安全审计，不是诊断日志（§3.3）。

---

## 6. 插件 / 市场前瞻（目标⑤，设计先行、实现最后）

核心判断（来自 Claude Code）：**我们的插件大部分是内容，不是代码**。
LunaMoth 已有五种声明式内容目录，市场要卖的是"角色包"。

### 6.1 包格式（chara pack）

```
my-chara-pack/
├── lunamoth-pack.json        # 清单：name/version/author/description/license
├── characters/  worlds/  toolpacks/  skills/  themes/   # 全部可选
└── mcp.json                  # 可选：随包声明的 MCP server（装时明示风险，默认不启）
```

- 安装 = 解包进 `~/.lunamoth/packs/<name>/`，各内容目录加入对应搜索路径
  （skills 已经是三层搜索，其余照搬同一模式：own → user → **packs** → bundled）。
- **市场 = 一个 git 仓库 + `market.json` 索引**（Claude Code marketplace 模式）：
  `lunamoth market add <repo>` / `lunamoth install <pack>`（= 浅 clone + 校验清单）。
  零服务器、零基建，ST 卡片站的卡直接 PNG 导入不受影响。

### 6.2 代码插件（远期，hermes 模式）

- 前置条件：`tools/registry.py` 声明式注册表（本来就在 roadmap）。
  内置工具自己先变成 registry 的客户——内外一套机制，插件才不是二等公民。
- `plugin.yaml` + `register(ctx)`；ctx 暴露：`register_tool`（进 gateway 同一审计/
  allowlist 管道）、`register_command`（进 protocol/commands.py）、hook 点先开四个：
  `pre/post_tool_call, on_session_start/end`。
- 更便宜的中间形态可以先做 **hooks**（Claude Code 式）：settings 里配置生命周期点
  跑 shell 命令，零插件加载器成本。
- 安全姿势与 MCP 一致：装代码插件 = 信任决定，文档明示；插件不持有 key
  （hermes `ctx.llm` 门面模式备用）。

---

## 7. 分阶段迁移（每阶段独立可完成、可单独验收、可并行分工）

原则：**契约先行，搬家其次，传输最后**。每阶段结束全测试绿 + 双 README roadmap 更新。

| 阶段 | 内容 | 改动面 | 依赖 | 适合谁 |
|---|---|---|---|---|
| **P0 日志** | obs/log.py + broker.py + 全库打点 + --debug + doctor 集成 | 纯增量，零行为变化 | 无 | 任一 agent，随时可做 |
| **P1 事件流** | protocol/events.py；llm.py/agent.py 产出事件取代 \x01-\x04；TUI/terminal 改为事件消费者；codec + `run -p --stream-json` | llm/agent/tui/terminal | 无 | **一个 agent 独占**（核心改动，勿并行碰这四个文件） |
| **P2 搬家** | §3.1 包布局；旧路径留 re-export shim 一个版本；test_architecture.py 上线 | 全库路径（机械） | P1 后做，避免边搬边改 | 一个 agent 一次完成，**事先与邻居约时间窗** |
| **P3 门面** | CharaHandle + commands.py 统一命令注册表；tui 拆分为 front/tui/ 多文件；删 20 处直接属性访问 | front/ + protocol/ | P1, P2 | 可与 P0 并行 |
| **P4 服务** | server/ dispatch + stdio + ws；`lunamoth serve`；TUI `--connect` 远程模式 | 纯增量（front 不改，因为 P3 已隔离） | P3 | 任一 agent |
| **P5 插件** | tools/registry.py + 内置工具迁入 + pack 清单/install/market 命令 + hooks | tools/ + cli | P2（registry 位置） | 可与 P4 并行 |

里程碑对账：P1 完成 → 控制字符协议消亡；P3 完成 → 目标②④的进程内部分达成，
桌面/网页开发可启动（先打同进程 CharaHandle）；P4 完成 → roadmap 的 remote gateway
达成；P5 完成 → 市场就绪。

### 风险与对策

- **与邻居（上下文压缩）撞车**：P2 搬 `compaction.py` 只动路径不动内容；
  P1/P2 动 llm/agent/tui 前在 CLAUDE.md 留"施工中"标记，约定时间窗。
- **shim 周期**：旧导入路径（`from lunamoth.tools import ToolGateway`）保留一个
  过渡版本再删，期间双方提交都不至于断。
- **行为回归**：P1 是唯一有行为风险的阶段——验收标准定为"TUI/plain 渲染逐像素
  不变、transcript 内容不变"，靠现有 77 测试 + 新增事件流黄金测试兜底。

---

## 9. ✅ 已实现：说话信道 · 聊天优先 · 时间感（F1，随 P0–P3 落地）

> 目标画像：chara 是"活在电脑里的存在"——有自己的节奏过自己的生活；用户开口时
> 放下手头的事专心聊天；用户想看细节就进 CLI/TUI（微信/Telegram 只收"它想说的话"）；
> 它对现实时间有感知、知道自己的时间流速与现实不同、可以自己决定休息。

### 9.1 两个输出语域（说话信道）

- 事件层：`TextDelta` 自带 `channel` 字段（**重构第一天就有**，免得日后破协议）：
  - `say` — 对用户说的话。所有前端都投递：消息平台发消息、TUI 聊天流高亮、桌面端可通知。
  - `muse` — 自语/工作叙述/过自己的生活。只有"全景前端"（TUI/桌面端工作视图、
    spotlight）展示；微信/Telegram 适配器直接丢弃。
- 引擎规则（自动切换 + 主动工具，二者并存）：
  - **engaged（用户在聊）时**：模型的普通流式输出就是说话 → channel='say'。
    聊天保持流式、零工具开销。
  - **自主状态时**：普通输出 = muse；要触达用户必须显式调用 **`speak` 工具**
    （args: text；它产生一条完整的 say 事件）。"知会用户"因此成为一个深思熟虑的动作，
    模型自己判断什么值得说——这正是 owner 要的微信/TG 体验。
  - speak 进 ToolGateway 同一审计/allowlist 管道；工具描述保持中性（何时值得说话
    是角色卡的事）。

### 9.2 聊天优先（engagement）

- `presence/` 新增 engaged 状态：用户消息 → engaged=True 且**挂起自主节奏**
  （手头工作放下，下回合专心对话）；用户静默超过 `quiet_period`（默认 5min，
  settings/卡可调）→ engaged=False，自主生活恢复。
- 现有 attach-grace 是它的特例，届时并入；`patience` 保留为自主节奏的默认步长。
- rules 层加一条中性约定（仅限有工具的 chara）：用户开口时，放下工作、全神贯注；
  你的工作等得起。

### 9.3 时间感（不污染上下文的前提下对齐现实）

- **时间戳搭空 user message 的便车**：自主 tick 本来就是 ephemeral 的空用户消息
  （不持久、不进历史），让它携带当前真实时间——模型每次醒来都知道几点，
  而上下文里**零**时间戳残留。
- **大间隔标注**：用户长时间（阈值如 30min）沉默后再开口，这条消息附一次时间注记
  （会持久，但按构造就稀疏）。日期可进 env facts 行（日粒度，不伤 prompt cache）。
- **自主节奏 = 自定闹钟**：新增 `rest(minutes, reason?)` 工具——chara 自己决定下次
  醒来时间（引擎 clamp 到合理区间），不调用则退回 patience 默认步长。
  参考 Claude Code 动态 loop 的 ScheduleWakeup 模型。"一连串工作后停顿"由它自己决定。
- rules 层一句中性事实陈述：你的回合是脉冲式的，回合之间现实时间在流逝；
  你看到的钟是真实世界的钟。
- **架构归属**：chara 的"生活节奏"必须活在后端（daemon，今后是 serve 进程），
  与是否有前端 attach 无关——这是"活在电脑里"的字面要求，也是 P4 的隐含动机。

### 9.4 对各阶段的影响

- P1：`TextDelta.channel` 字段 + engaged/自主两态的 channel 判定点预留（先恒为 say/muse 的现状等价）。
- ✅ F1 已实现（speak/rest 工具、/quiet engagement、时间戳搭车、大间隔注记、env 日期）——重构后第一个"协议原生"功能，验证通过。
- `rest` 与消息平台适配器（Telegram 等）随 P4/P5 节奏另行排期。

## 10. 多 agent 协作规约（重构后长期生效）

1. **protocol/ 是宪法**：events/commands/codec 的改动须 owner 过目；加事件向后兼容
   （客户端忽略未知事件类型），删/改字段走 `protocol_version`。
2. **域所有权**：一次只允许一个 agent 改一个域（core/tools/front/…）；跨域 feature
   先改 protocol（加事件/命令），后端前端随后可由不同 agent 并行实现——
   这正是"前后端 feature 协同更新"的工作流。
3. **test_architecture.py 永远在 CI 路径上**：依赖方向回归 = 红灯。
4. CLAUDE.md 模块地图随 P2 同步重写；每阶段完成更新本文档的勾选状态。
