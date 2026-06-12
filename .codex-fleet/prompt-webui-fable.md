# 任务：LunaMoth web 前端重设计（front/web 全面翻新）

你是一位资深前端工程师 + 设计师，负责把 LunaMoth 的 web 渲染器
（`src/lunamoth/front/web/` — 无构建步骤的 vanilla HTML/CSS/JS）翻新成
产品级界面。先读 `CLAUDE.md`（约束性）、`docs/desktop/design.md`、
`docs/desktop/supervisor.md`（协议契约）、以及竞品研究
`.codex-fleet/hermes-ui-notes.md`（28 张 Hermes Desktop 截图的完整分析——
设计基调以它为准，但只"学其骨"，品牌气质保持 LunaMoth 自己的）。

## 施工纪律

- 分支 `webui`，在独立 worktree 工作；**只改 `src/lunamoth/front/web/`、
  i18n 文案，以及（如确有需要）`apps/desktop/` 的 Electron 薄壳**。
  不碰 protocol/、server/、core/。web 是 Electron 加载的同一份代码——
  正常情况下壳零改动；若新 UI 需要壳配合（如通知文案），保持 preload
  只暴露 `lunamothNative.notify` 的最小面。如果发现缺一个后端 RPC 才能
  做某个 UI，不要自己实现——写进 `.codex-fleet/webui-needs.md` 留给主管，
  UI 上先做出"等待后端"的占位形态。
- 不合并不推送；完成后留 commit，主管验收合并。
- UI 框架文案一律走 `i18n.js`（zh/en 双语）；chara 的话保持卡片语言。
- 测试：`uv run python -m pytest -q` 必须全绿（web 是纯协议客户端，
  不应破坏任何东西）；手动验收路径见文末。
- 前置依赖：supervisor 分支已合并 main 之后再开工（rpc.js 的 seq/rejoin、
  `life.state` 帧、`superchat.read` RPC、`patience` 字段都来自它）。

## 设计基调（源自 Hermes 研究，hermes-ui-notes.md 有全部细节）

1. **三层框架 + 常驻底部状态栏**：左侧栏（~210px：board 入口 + chara
   列表）· 主画布 · 底部状态栏（左：chara 生命状态/网关点/隔离徽章/网络；
   右：上下文用量条 used/真实窗口、会话计时、模型+思考强度 chip（点击=
   热切换弹层）、版本）。状态栏就是"系统托盘"。
2. **聊天列 ~720px 居中、内容全部居左**。用户消息=细边框盒子（不是右侧
   气泡），chara 正文=裸排版。五信道保持现有区分但作为"同一排版的变奏"：
   muse=暗淡斜体条、say=正文、⚡Super Chat=主题色浅染卡片、思考=折叠行
   （带一行灰色摘要）、工具=动词 chip（"Run · <cmd> 1.2s"，可展开输出）。
   空聊天状态=该卡的 SVG 头像 + 名字 + tagline（杀掉"屏幕空旷"问题，
   也给每张卡一个品牌时刻）。
3. **小型大写字距标题**（STATUS / GATEWAY / MEMORY…）作为全局唯一的分组
   语言；一行式设置行（粗体标签 + 一行灰色理由 + 右侧控件）；留白靠右侧
   面板吃掉，不靠放大间距。
4. **Appearance 里加 "Product | Technical" 工具显示开关**：Product 隐藏
   原始载荷（OC 创作者），Technical 显示完整输入输出（开发者）。一个开关
   解决三受众问题。

## 需求清单（owner 验收标准）

### A. 右侧面板：「状态」与「设置」分层（本次的核心重构）

- 聊天页右侧常驻面板（可折叠）。顶部是**状态区**——高频、温和、一眼可读，
  点击即改：
  - 模型与提供商（点击=热切换弹层，含思考强度 Minimal–Max 五档）
  - 上下文用量（used/真实窗口 + 百分比条）
  - 沙盒隔离（dir/sandbox/docker）与工作目录
  - 网络 on/off（点击切换，走 `/net`）
  - **自主运行 on/off**（英文 live on/off；取代旧"持续运行/对话模式"标签，
    走 `/mode live|chat`；聊天框右上角的旧模式切换控件删除）
  - 思考强度、记忆用量、已启动的网关、可用 tools 与权限
- 状态区之下是**设置选单**：网关 / 能力(toolpack+tools) / 记忆 / 文件 —
  点击跳转右侧面板的对应详情页（面板内导航，不是新页面）。点状态里的
  网关行也跳到网关详情。
- 旧"设置按钮弹出菜单"里的动作（整理记忆、安静一会儿、思考、联网、
  重新开始）全部移进右侧面板对应区；**reset/重新开始放设置最底部**
  （危险区样式）。斜杠命令在聊天框仍然可用，但 UI 引导走右侧面板。
  原则：**凡有 /command 的能力，右侧面板都应有入口**（/quiet /tempo
  /patience /embodiment /net /mode /memory /reset…——用 handle.command()，
  命令注册表是现成的）。

### B. 存在感知（presence legibility）

- 渲染 `life.state` 帧（supervisor 广播）：
  - `waiting`（engaged）→ 状态条"在等你回复 · Waiting for you"
  - `idle_countdown` → **RPG 式耐心进度条**：倒计时到 next_cycle_at，
    总长 = patience÷tempo，旁边显示大约时间（"约 8 分钟后做自己的事"）
  - `working` → "在做自己的事"+现有工作指示动画
  - `resting` → "在休息，HH:MM 醒来"
  - `backoff` → 醒目的错误态（含 detail）
- attach/detach 的感知：进入聊天时一条居中淡行"✓ {char} 知道你来了"；
  离开（关页/切 chara）后再回来，若期间有 on_detach/gap，渲染相应提示。
- patience 可在设置里调（`/patience <sec>`，状态区显示当前值）。

### C. Super Chat 已读

- ⚡气泡在页面可见时渲染 → 调 `superchat.read {name, ts}`，气泡出现安静
  的 ✓已读标记。
- Board 的 Super Chat 流显示未读角标（`superchat_unread`），点进聊天后
  清零。

### D. 卡片浏览与工坊

- **浏览卡片不再展示原始 JSON**：渲染成卡片视图——SVG 头像 + 主题色、
  名字、tagline、persona 摘要、世界书条目数、种子目标、toolpack、
  embodiment 徽章；"查看原始 JSON"作为底部折叠项保留给开发者。
- **工坊改为模态层 + 背景虚化**（backdrop-filter blur + 半透明遮罩），
  不再全屏接管——背景的 board 仍隐约可见，不让人不安。
- AI 生成完成后的编辑表单字段顺序（鼓励用户改写的放最上面）：
  1. 两张并排小卡：**chara 名字** | **用户名字（user_name）**
  2. **用户自己的设定**（persona，写"你是谁"）
  3. chara 设定（description/personality/scenario）
  4. 其余（开场白、世界书、目标、SVG、主题色、embodiment 选择）
  全部字段可编辑后再保存。
- **唤醒卡片时必须能选 toolpack**（现在不能编辑 tools 是已知缺陷）；
  唤醒后 toolpack/网络/隔离等也要能在右侧面板运行时改（有命令的走命令）。

### E. 网关（per-chara，刻意不同于 Hermes 的全局连接器页）

- 网关属于每个 chara：从 chara 的右侧面板「网关」进入，**弹出卡片 +
  背景虚化**配置。
- 详情页公式照抄 Hermes：身份头 + **三枚独立状态 chip**（已启用/未启用 ·
  已配置/待配置 · 网关运行中/已停止）→ GET YOUR CREDENTIALS 白话步骤 +
  外链 → REQUIRED 字段 → RECOMMENDED（带安全理由，如 allowed_senders
  "不填则任何人都能召唤你的 chara"）→ ADVANCED 折叠 → 左下启用开关 +
  右下保存。平台：wecom / weixin（iLink 扫码）/ qq（OneBot）。
  weixin 的二维码：渲染 `qrcode_img_content`（后端就绪前先做占位态）。
- 状态数据来自 board 的 `gateway` 字段与 `gateway.start/stop/status` RPC。
- **配置读写 RPC 契约**（主管在集成时落地后端，UI 直接按此编码）：
  - `messaging.get {name}` → `{adapters: {<platform>: {…}}, allowed_senders: [],
    refusal_text, enabled}`；秘密字段（secret/encoding_aes_key/access_token）
    回传为掩码 `"••••"`，UI 留空=不修改。
  - `messaging.save {name, config}` → 写回 messaging.json（掩码值跳过）。
- **三平台字段表**（messaging.json → `adapters.<platform>`）：
  - `wecom`（企业微信自建应用）：REQUIRED corp_id / secret / agent_id /
    token / encoding_aes_key；RECOMMENDED to_user、顶层 allowed_senders；
    ADVANCED host / port(8128) / path / api_base。提示语写明需要公网回调。
  - `weixin`（个人微信 iLink，扫码）：无必填字段——凭据是扫码后自动持久化
    的状态文件；ADVANCED base_url / bot_type("3") / long_poll_timeout_ms /
    api_timeout_ms。配置页主体是**扫码流程区**：当后端提供
    `weixin.qr {name}`（返回 qrcode_img_content/状态）时渲染二维码 +
    轮询登录态；该 RPC 落地前做占位态（"启动网关后在终端扫码"），写进
    webui-needs.md。另以提示行注明：chara 只能主动联系"本会话中先开口
    过"的用户（context_token 机制）。
  - `qq`（OneBot v11 / NapCat）：REQUIRED url(ws://…) / peer_id（"你自己的
    QQ 号"）；RECOMMENDED access_token、allowed_senders；步骤区写白话三步
    （跑 NapCat → 在它的 WebUI 扫 QQ 码 → 开启 forward WebSocket 并粘贴
    地址）。

### F. 杂项

- 全局空状态都要说明"什么会填满它"。
- 错误必须指名修法（哪个 key、去哪改）——不做静默回退；设置里如出现
  类似 Hermes "Fallback Models" 的位置，渲染成一行声明
  "No fallbacks — failures are shown / 不做回退——失败会如实显示"。
- 模型默认 vs 热切换的措辞照抄 Hermes 的 scoping："默认应用于新会话；
  热切换只影响当前会话"（映射到我们的 defaults vs 每 chara config）。
- 多 key 管理（维护多把 key 任选）**本次不做**——后端 RPC 未就绪，
  留在 webui-needs.md。

## 协议契约（已由 supervisor 分支提供，不要自己发明帧）

- `life.state` 通知：`{state: working|waiting|resting|idle_countdown|backoff,
  next_cycle_at, rest_until, engaged_until, detail}`
- 重连：rpc.js 已带 seq/rejoin——不要再实现 attach 重放逻辑，只处理
  rejoin.gap 时的全量恢复 UI。
- `superchat.read {name, ts}`（hub RPC）；board 条目含 `superchat_unread`、
  `gateway`、`life`。
- `StateSnapshot.patience`；`/patience` 命令。
- 空闲循环由 supervisor 驱动，**前端绝不自己驱动 idle**。

## 验收路径（完成后逐条自测）

1. 打开聊天：空状态=头像+名字+tagline；底部状态栏齐全；右侧面板状态区
   每一项可读可点。
2. 说一句话→"在等你回复"；停止说话 quiet 秒后→耐心进度条走完→chara 开始
   做自己的事（working 动画）；`/rest` 后显示休息至几点。
3. 收到 Super Chat→⚡卡片→看到后出现✓已读→board 角标清零。
4. 浏览卡片=卡片视图非 JSON；工坊=虚化模态；生成后名字/用户设定在最上。
5. 唤醒流程能选 toolpack；右侧面板能运行时改网络/模式/思考强度/patience。
6. 网关配置=虚化模态+三状态 chip；i18n 中英切换无裸字符串；浅深色都不破。
