# HANDOVER — 2026-06-12 day end

Two roles ran today on the owner's machine and both stop here. This file is
the ORCHESTRATOR-track harness for successors on any machine; the webui
Fable writes its own handover beside this one in docs/ (where the two
disagree about Track B, THEIRS wins — they hold the owner conversation).
Read `CLAUDE.md` first (binding constitution), then your role's section.
Delete this file once absorbed (handovers are transient, not documentation).

Repo state at handover: `main` = everything below, **192 passed** /
`uvx ruff check --select F src/lunamoth tests` clean. No unmerged branches,
no worktrees, no running codex. The owner's charas under `~/.lunamoth` keep
living (one daemon + its self-built services) — they are residents, not
garbage.

## What landed today (review `git log` for detail)

1. **lunamothd supervisor** (`docs/desktop/supervisor.md` is the spec):
   resident process owning chara + gateway children; `seq` ring + `rejoin`
   replay (client reconnect resumes in place); single-driver takeover (4408);
   server-side idle driving (the ONLY idle driver) gated by
   quiet/rest/backoff/patience÷tempo; `life.state` notifications; crash =
   visible state, never silent restart; `daemon.json` + `lunamoth daemon
   stop|status`; `lunamoth start` delegates to a live supervisor.
2. **patience is a per-chara setting** (default 600 s, card hook, `/patience`,
   snapshot field). Backstory: the old 2-second daemon default burned a real
   OpenRouter key's daily limit — never reintroduce tiny idle cadence.
3. **Messaging adapters**: personal WeChat over Tencent's official iLink
   ClawBot API (QR login, stdlib long-poll, state in 0600
   `weixin_state.json`, errcode −14 visible) + QQ as OneBot v11 forward-WS
   client to user-run NapCat. Research dossier:
   `.codex-fleet/astrbot-gateway-notes.md`.
4. **Attach never wakes a resting chara** (owner decision): presence fact
   only; a user MESSAGE always wakes; see `protocol/api.py attach()`.
5. **Quinn 小Q is the default card** (owner-authored, `cards… see below`):
   tag convention pending in the cards wave; CLAUDE.md updated.
6. Earlier today (already reviewed): tempo+embodiment knobs, card studio,
   desktop reliability polish, five-channel legible chat + Super Chat,
   WeCom gateway, Electron shell.

## Conventions that bit us today (obey them)

- **Every codex brief MUST carry the discipline block** (no merge, no push,
  no other worktrees, stop after the .done flag). A codex self-merged to main
  today because the brief omitted it; another kept running self-directed
  "acceptance" work after printing its summary — kill stragglers after the
  .done flag appears (`ps aux | grep codex`).
- After any fleet wave, audit `git log main` for commits you didn't make.
- Commit/push only when the owner asks. Stage only your own files.

## Track A — orchestrator successor (the 主管 Fable)

You are the planner/integrator. Deterministic coding goes to codex
(`sc codex exec --dangerously-bypass-approvals-and-sandbox -C <worktree> - <
brief.md`, tmux-managed, one worktree per branch, briefs under
`.codex-fleet/`); you design, review, integrate. Queue, in order:

1. **Dispatch `.codex-fleet/brief-cards-one-file.md`** (ready, includes the
   Quinn default-tag section + themes/ retirement). Branch `cards-one-file`.
   It was aborted mid-exploration today, nothing lost.
2. **After that merges, implement the web-facing RPC batch yourself** (small,
   conflicts with nothing once cards lands): `works.read {name, rel}`
   (sandbox-confined file preview, ~512KB cap), `messaging.get/save {name}`
   (masked secrets), `card.avatar_draft` (2–3 sanitized SVG candidates),
   `weixin.qr {name}` (QR + login-state poll for the web gateway page).
   Specs: `.codex-fleet/webui-needs.md` (the webui Fable's requirement list —
   treat it as the contract).
3. **PTY over WS** (`/chara/<name>/pty`, shell inside the chara's isolation,
   Hermes `/api/pty` shape): write a brief, dispatch to codex. The
   "should the chara know you touched its home" question is a curriculum
   decision — leave the transcript untouched, note the open question.
4. Then the roadmap (CLAUDE.md) — next by audience-priority: chara curriculum
   eval (cross-worldview test cards), GM layer via stream_event, Telegram
   adapter (trivial after qq.py — long-poll, no public URL).

Acceptance ritual per wave: review diff against the brief (wire format /
architecture boundaries / no-fallback policy are MY review, not the suite's),
full pytest + ruff, live 60-second path, merge, then a 5-minute owner demo
script.

## Track B — webui successor (front/web + Electron Fable)

Check docs/ for the handover written by your direct predecessor first — it is
authoritative. The summary below is the orchestrator's record of the same
agreements (kept in case the other file is missing). Read, in order:

1. `.codex-fleet/prompt-webui-fable.md` — the base task (scope, gateway-page
   contract, acceptance path).
2. **The owner-decision overrides** (recorded by your predecessor; binding):
   - KEEP the current bubble chat style (owner likes it; Hermes's bare-prose
     look was rejected as 干巴巴). Add: avatar next to bubbles + header,
     empty state = big avatar+name+tagline, tool verb-chips with duration,
     collapsed thinking with one-line gray summary.
   - Right panel = resident, carries the IMPORTANT state (life, model+effort
     hot-swap, autonomous live on/off, net, isolation, context meter, memory,
     gateway) + settings menu; bottom bar = unimportant only (version, WS,
     session timer). Both sidebars drag-resizable, widths in localStorage.
   - Per-chara tabs: 对话 | 作品 | 终端 (works tab uses `works.list` +
     pending `works.read`; terminal tab needs the PTY endpoint — placeholder
     until Track A lands it). Views stay mounted; hash routes
     `#/chara/<n>{,/works,/term}`. The right-panel「文件」page is CANCELLED —
     merged into 作品.
   - Editable avatar modal (blur backdrop): AI regenerate (pending
     `card.avatar_draft`), theme-color swap (pure frontend), raw SVG textarea.
     No raster upload v1.
   - Mood layer: two-layer CSS vars (`--chara-accent` from theme_color; mood
     states only transform it, color-mix 8–15%, no layout shifts),
     `data-life` attr on chat root; waiting=breathing glow; working and
     idle_countdown = ONE register ("doing its own thing"); resting=dimmed
     room + placeholder "它在休息——说话会唤醒它" (input never looks
     disabled); backoff=desaturated + detail; prefers-reduced-motion → static.
   - State semantics: **waiting (quiet window) is THE user-facing progress
     bar** ("条走完我就去干自己的事"); idle_countdown/patience is mechanism,
     shown only as a small Technical-mode line. Settings copy: quiet =
     「等你多久」, patience = 「它自己生活的节拍」.
   - Remove the 【听着】 posture label (engine asserts no posture; factual
     labels only). Super Chat read = FADE the bubble, no ✓.
   - Attach-not-wake is now IMPLEMENTED backend-side: while resting, show the
     dimmed room, no "它知道你来了" line.
3. `.codex-fleet/hermes-ui-notes.md` — design-system reference (status-bar
   anatomy, connectors master-detail formula, model-picker popover, settings
   row grammar, Product|Technical switch).
4. `.codex-fleet/webui-needs.md` — what you're waiting on from Track A; build
   "waiting for backend" placeholder states, never implement backend
   yourself.

Discipline: branch `webui`, own worktree, only `front/web/` + i18n +
(if needed) `apps/desktop/`; commit there, no merge, no push; the Track A
Fable integrates. All five context channels stay visually distinct; chara
language follows the card; UI chrome bilingual zh/en.

## Loose ends register

- `stash@{0}` on the owner's machine: their old CLAUDE.md→docs move; owner's
  call to drop.
- `hermes ui/` (24 MB screenshots, owner's material, now gitignored): the
  notes file distills it; owner may delete the folder when done with it.
- WeCom/WeChat/QQ gateways are code-complete but none live-tested with real
  credentials; iLink protocol is young (endpoints shifted once already) —
  budget a fix round on first real login.
- Electron shell merged but never `npm run dev`-tested on a real display.
- supervisor test file is thin (83 lines); the IdleGate/FrameRing classes are
  injectable-clock testable — deepen when touching that area.
