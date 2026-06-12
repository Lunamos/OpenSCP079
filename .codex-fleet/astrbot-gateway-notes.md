# AstrBot messaging adapters — research notes for LunaMoth's gateway

Source: `reference/AstrBot` (AstrBotDevs/AstrBot, shallow clone @ 32cfcbf, 2026-06-10, v4.25.x era)
plus docs.astrbot.app. LunaMoth seam reviewed: `src/lunamoth/messaging/base.py`
(Adapter ABC: `run(inbox)` thread + `send(text)` + optional `close()`),
`gateway.py` (queue loop, allowlist, say-channel only), `wecom.py` (pure-stdlib
HTTP callback server + urllib send — the house style).

## How AstrBot does it

### Personal WeChat — the QR-scan path the owner saw is `weixin_oc` (Tencent-official iLink/ClawBot API)

The big news: **in March 2026 Tencent shipped an official Bot API for personal
WeChat** — the "ClawBot" plugin in the WeChat app, protocol name **iLink**,
endpoint `https://ilinkai.weixin.qq.com`, originally published as
`openclaw-weixin` (Tencent's official OpenClaw connector). This is the first
sanctioned personal-account bot channel; it replaces the reverse-engineered
pad-protocol era. AstrBot v4 removed gewechat/WeChatPadPro from core and ships
`weixin_oc` ("个人微信") as the current personal-WeChat adapter.

Files (all under `reference/AstrBot/astrbot/core/platform/sources/weixin_oc/`):

- `login_registration.py` — login constants + flow:
  - `GET ilink/bot/get_bot_qrcode?bot_type=3` → `{qrcode, qrcode_img_content}`
  - long-poll `GET ilink/bot/get_qrcode_status?qrcode=...` (header
    `iLink-App-ClientVersion: 1`) until `status == "confirmed"` →
    `{bot_token, ilink_bot_id, ilink_user_id, baseurl}`.
  - Defaults: base `https://ilinkai.weixin.qq.com`, CDN
    `https://novac2c.cdn.weixin.qq.com/c2c`, long-poll timeout 35 s.
- `weixin_oc_adapter.py` (1777 lines) — the runtime:
  - **No extra service, no public callback.** Plain HTTPS to Tencent. Receive =
    long-poll `POST ilink/bot/getupdates` with a server-issued cursor
    (`get_updates_buf`, persisted) (line ~1567). Send =
    `POST ilink/bot/sendmessage` with an `item_list` (line ~876).
  - Auth headers: `Authorization: Bearer <bot_token>`,
    `AuthorizationType: ilink_bot_token`, random base64 `X-WECHAT-UIN`
    (`weixin_oc_client.py:44`).
  - **QR display**: rendered as ASCII in the log via the `qrcode` pip package,
    plus an `api.qrserver.com` image link; the WebUI shows
    `qrcode_img_content` in the create-bot dialog (adapter lines 1039–1089;
    QR valid 5 min, auto-refresh up to 3×).
  - **Session persistence**: `_save_account_state()` writes
    `weixin_oc_token / account_id / sync_buf / base_url / context_tokens`
    back into the platform config (lines 560–584); restarts reuse the token —
    no rescan while the session is valid.
  - **context_token gotcha**: every inbound message carries a per-user
    `context_token` (line ~1490); `sendmessage` REQUIRES it (lines 868–875).
    So the bot can only message users who have messaged it, and tokens go
    stale (errcode −14 = session timeout → re-login path).
  - **1:1 only**: every inbound is `MessageType.FRIEND_MESSAGE` (line 1532);
    no group support in this snapshot.
  - Media: CDN upload/download with AES-128-ECB + PKCS7 (`weixin_oc_client.py`,
    pycryptodome). Inbound voice arrives WITH WeChat-cloud transcription text
    (`voice_item.text`). Outbound: text/image/video/file; no voice send.
  - Typing indicator: `ilink/bot/getconfig` + `ilink/bot/sendtyping`.
  - Deps: `aiohttp`, `qrcode`, `pycryptodome` — but **text-only needs none of
    the crypto**, and the HTTP is ordinary JSON-over-HTTPS.
  - User-visible UX: scan QR with the phone WeChat (iOS ≥ 8.0.70 /
    Android ≥ 8.0.69, with the ClawBot plugin); the bot then exists as a
    bot identity (`ilink_bot_id`) bound to that account.
- Config schema in `astrbot/core/config/default.py:11-40,414-420`:
  `weixin_oc_base_url`, `weixin_oc_bot_type` ("3"), `weixin_oc_qr_poll_interval`,
  `weixin_oc_long_poll_timeout_ms` (35000), `weixin_oc_api_timeout_ms`,
  `weixin_oc_token` (auto-filled after scan).

**Risk story**: this is Tencent-official — docs carry no ban warnings. The
protocol is publicly documented by the community (hao-ji-xing/openclaw-weixin
spec, photon-hq/wechat-ilink-client, wechat-clawbot on PyPI), so speaking it
directly is the same thing AstrBot does.

### Personal WeChat — the legacy paths (for completeness)

- **gewechat**: upstream discontinued (early 2025); adapter long removed.
- **WeChatPadPro** (now `wechatpadpro_legacy` in docs; adapter existed through
  v3.5.x, removed from the v4 core tree — fetched from tag v3.5.20 for
  reference): a **separate self-hosted Docker service** (port 8059, `ADMIN_KEY`
  env) implementing the reverse-engineered iPad protocol. AstrBot connected via
  `POST /admin/GenAuthKey1` → `POST /login/GetLoginQrCodeNew` → poll
  `GET /login/CheckLoginStatus`, then received messages over
  `ws://host:8059/ws/GetSyncMsg?key=...` and persisted `auth_key`/`wxid` in
  `wechatpadpro_credentials.json`. Real ban risk (unofficial protocol),
  upstream needs authorization codes, extra service to babysit. Superseded —
  do not copy.

### QQ — two routes

1. **OneBot v11 via NapCat/Lagrange** —
   `astrbot/core/platform/sources/aiocqhttp/aiocqhttp_platform_adapter.py`:
   - AstrBot runs a **reverse-WebSocket SERVER** (`CQHttp(use_ws_reverse=True,
     access_token=...)`, default `0.0.0.0:6199`, lines 55–62, 419–437); NapCat
     (or Lagrange) is the client that dials `ws://host:6199/ws`.
   - Config: `ws_reverse_host`, `ws_reverse_port`, optional `ws_reverse_token`.
   - Events arrive as OneBot v11 JSON (post_type message/notice/request,
     message segments array); replies/actions are JSON-RPC-ish
     `call_action("send_private_msg"/"get_msg"/...)` over the same socket.
     Segment handling distinguishes NapCat vs Lagrange quirks (file URLs,
     lines 253–298).
   - **Login lives entirely in NapCat**: the user installs NapCat (Docker or
     binary; it embeds the QQNT core), opens NapCat's own WebUI, scans a QQ QR
     there, then adds a "WebSocket client" pointing at the bot. AstrBot never
     touches QQ credentials. Lagrange (NTQQ reimplementation, C#) is the same
     shape. Stability: mature, the de-facto standard; unofficial, so ban risk
     is nonzero but in practice low for normal personal-bot use.
   - Dep: `aiocqhttp>=1.4.4` (which drags in Quart).
2. **QQ official open platform** — `sources/qqofficial/` (websocket, `qq-botpy`
   SDK: appid+secret, gateway WS, `on_group_at_message_create` etc.) and
   `sources/qqofficial_webhook/` (`qo_webhook_server.py`, appid+secret,
   Ed25519-signed callbacks). No QR — requires registering a bot on
   q.qq.com (developer account, sandbox→production review). Official and
   stable but: group messages only on @-mention, strict frequency/content
   limits, and a registration burden unsuited to "my chara talks to me."

## Recommended path for LunaMoth

### Personal WeChat: speak the iLink/ClawBot API directly (new `weixin` adapter)

This is exactly "微信扫码就能连接", with no extra service and no ban-risk
asterisk. It also fits LunaMoth unusually well: 1:1-only matches one chara ↔
its human, and `speak` maps to `sendmessage`.

- **Mechanism**: port the weixin_oc flow into a sync, stdlib-style adapter
  (mirroring `wecom.py`): `urllib.request` for all JSON calls.
  - `run(inbox)`: if no saved token → QR login loop (GET get_bot_qrcode,
    print QR, long-poll get_qrcode_status); then forever long-poll
    `POST ilink/bot/getupdates` (35 s timeout) and push
    `InboundMessage(sender_id=ilink_user_id, text=...)`.
  - `send(text)`: `POST ilink/bot/sendmessage` with the stored per-user
    `context_token` (persist alongside the token).
- **Config fields** (`messaging.json` → `adapters.weixin`): none strictly
  required to start; optional `base_url`, `bot_type` (default "3"),
  `long_poll_timeout_ms`, `api_timeout_ms`. Credential state
  (`token`, `account_id`, `sync_buf`, `context_tokens`) auto-persisted to a
  state file in the session dir (e.g. `weixin_state.json`) — NOT hand-edited
  config, mirroring AstrBot's auto-fill.
- **Login UX**: QR printed in the terminal at `lunamoth` adapter start
  (ASCII via the `qrcode` package, like AstrBot, plus a fallback
  `api.qrserver.com` URL line); later we can surface `qrcode_img_content` in
  the web deck. Rescan only when the session dies (errcode −14).
- **Dependencies**: text-only = **stdlib only** (urllib + json), matching
  wecom.py. `qrcode` (pure-python) for the terminal QR — put it in the
  existing `messaging` extra; without it, print the qrserver URL. Media
  send/receive would need pycryptodome (AES-ECB CDN crypto) — defer; note
  that inbound voice already arrives transcribed as text, so it degrades
  gracefully.
- **Receive/send mapped to our ABC**: long-poll thread = `run()`; `reply`
  field unused (single configured peer is fine, but keep `context_tokens`
  keyed by sender so allowlisted multi-user works). `max_message_length`:
  unknown hard limit; start conservative (~4000 chars) and rely on
  `split_text`.
- **Risks**: protocol is official but young (Mar 2026) — endpoints/fields may
  move (AstrBot already adapted once); `context_token` expiry means
  spontaneous idle `speak` fails until the human messages once per session —
  the gateway already tolerates send failures, but we should log it clearly;
  requires the human's WeChat app to be recent enough for ClawBot.

### QQ: OneBot v11, user runs NapCat, we connect as a **forward-WS client**

- **Mechanism**: NapCat (user-run, open-source, Docker or binary; QQ QR login
  happens in NapCat's own WebUI) exposes a OneBot v11 **WebSocket server**
  (e.g. `ws://127.0.0.1:3001`, optional access token). LunaMoth dials it as a
  client — the inverse of AstrBot's reverse-WS, chosen so WE never run a
  listener: one connect call, no server lifecycle, perfect for the threaded
  Adapter. (NapCat supports both directions; forward WS is a checkbox in its
  WebUI.)
- **Protocol**: single socket carries events (JSON, `post_type == "message"`,
  `message` as segment array — concatenate `text` segments) and API calls
  (`{"action": "send_private_msg", "params": {"user_id": ..., "message": ...},
  "echo": ...}`). `sender_id` = QQ number (allowlist-ready).
- **Config fields**: `url` (ws://…), `access_token` (optional), `peer_id`
  (default QQ to deliver idle says to; otherwise reply via `InboundMessage.reply`
  carrying user_id/group_id).
- **Dependencies**: `websockets` — already declared in the `server` extra;
  add to `messaging` extra too and use `websockets.sync.client.connect`
  (sync API fits `run()` threads, auto ping/pong). Pure-stdlib alternative if
  we ever care: NapCat's HTTP server (send) + HTTP-POST event push (receive),
  identical shape to wecom.py — but WS is one connection and less user config.
- **Login UX**: entirely NapCat's — user scans the QQ QR in NapCat's WebUI
  once; NapCat persists the QQ session. We document "run NapCat, enable
  forward WS, paste the URL into messaging.json".
- **Risks**: NapCat is unofficial (NTQQ-based) — low-but-nonzero ban risk,
  user-owned; NapCat updates occasionally break segment formats (AstrBot
  carries NapCat/Lagrange special-casing for files — text-only avoids almost
  all of it); reconnect/backoff on socket drop is on us (retry loop in
  `run()`).
- **QQ official platform**: skip for now. No QR, developer registration +
  review, @-only group replies, rate limits — wrong fit for a personal chara.
  If ever needed it's a separate `qqofficial` adapter (appid/secret, botpy-or
  raw gateway WS).

## Open questions

- **iLink API stability/ToS**: no published rate limits or hard message-length
  limit found; unknown whether Tencent will gate `get_bot_qrcode` (it currently
  needs no pre-registration). Worth a quick probe with curl before building.
- **context_token lifetime**: AstrBot persists tokens and handles errcode −14
  by re-login, but the actual TTL (hours? days? per-conversation?) is
  undocumented — affects how reliable unattended `speak` is on WeChat.
- **Group chat on iLink**: absent from AstrBot's adapter today; unclear if the
  protocol supports it at all yet.
- **bot_type values**: AstrBot hardcodes "3"; other values undocumented.
- **NapCat vs Lagrange default recommendation**: AstrBot docs lead with
  NapCat; Lagrange is leaner (no QQ client bundled) but its OneBot field
  quirks differ. Proposed: document NapCat, accept both (we only need text).
- **Does the `messaging` extra split** (wecom needs `cryptography`, weixin
  needs `qrcode`, qq needs `websockets`) — one extra or per-adapter extras?
