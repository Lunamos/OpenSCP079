<h1 align="center">LunaMoth 🌙</h1>

<p align="center"><i>An agentic character tavern — character cards, world books, tool packs, and hard limits, composed at launch.</i></p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-blue.svg" alt="License: Apache-2.0"></a>
  <a href="pyproject.toml"><img src="https://img.shields.io/badge/python-3.11%2B-blue.svg" alt="Python 3.11+"></a>
  <a href="README.zh-CN.md"><img src="https://img.shields.io/badge/文档-简体中文-9fd9ff.svg" alt="简体中文"></a>
</p>

<p align="center">
  <a href="#roadmap">Roadmap</a> ·
  <a href="#features">Features</a> ·
  <a href="#quick-start">Quick Start</a> ·
  <a href="#connecting-a-model">Models</a> ·
  <a href="#content">Content</a> ·
  <a href="#license--acknowledgements">License</a>
</p>

<p align="center">English | <a href="README.zh-CN.md">简体中文</a></p>

---

**LunaMoth is a runtime for agentic roleplay characters.** Unlike a plain chat frontend, a LunaMoth character can actually *do* things — run code, read and write files, manage its own durable memory — but only through an allowlisted tool gateway, inside a sandbox, with every call audited. You pick the model, the character card, the world book, the tool pack, and the limits; the runtime composes them into one session:

```text
[character card] + [world book] + [tool pack] + [bounded memory] + [sliding context]
```

It borrows the best of three worlds: the agent runtime of [Hermes](https://github.com/NousResearch/hermes-agent), the content ecosystem of [SillyTavern](https://github.com/SillyTavern/SillyTavern), and the session/remote-access ergonomics of [cc-switch](https://github.com/farion1231/cc-switch).

## Roadmap

- [x] SillyTavern-compatible character cards & world books
- [x] Composable tool packs with native tool calling
- [x] Bounded auditable memory, single-terminal split TUI with themes
- [x] **One-line installer & `lunamoth` CLI** — `curl | bash`, setup wizard, self-update
- [x] **Named sessions** — `lunamoth new/ls/attach/rm`, each with its own config & sandbox
- [x] **Isolation selector** — `dir` / `sandbox` (OS jail: sandbox-exec / bubblewrap) / `docker` per session
- [ ] **Persistent server sessions** — detached background sessions you can re-attach to (today: run inside tmux/screen)
- [ ] **Remote TUI** — beyond the `ssh host -t lunamoth attach NAME` baseline: a gateway for public-IP/VPS access (high priority)
- [ ] **Web UI** — remote browser access to running sessions (low priority)

## Features

<table>
<tr><td><b>SillyTavern-compatible content</b></td><td>Import V2/V3 character cards (PNG or JSON) and world books directly; <code>{{char}}</code>/<code>{{user}}</code> macros, <code>first_mes</code>, embedded <code>character_book</code>, and keyword-triggered lore entries all work.</td></tr>
<tr><td><b>Native tool calling</b></td><td>Tools are exposed via the OpenAI tool-calling protocol; the agent loop streams text and executes tool calls mid-turn.</td></tr>
<tr><td><b>Composable tool packs</b></td><td>Capability bundles (<code>toolpacks/*.json</code>) declare exactly which tools a character gets. No pack, no powers.</td></tr>
<tr><td><b>Sandboxed execution</b></td><td>Python runs in a subprocess with a workspace path guard, module blocklist, and resource limits; switch to a Docker backend (<code>--network none</code>, read-only rootfs, memory/CPU/pid caps) for a stronger boundary.</td></tr>
<tr><td><b>Bounded, auditable memory</b></td><td>Durable memory is a token-capped file the character edits through tools, not an unbounded database; every tool call lands in <code>sandbox/logs/audit.jsonl</code>.</td></tr>
<tr><td><b>Idle self-talk loop</b></td><td>Optionally let the character keep thinking between your messages (<code>--forever</code>), with capped frequency, history, and memory growth.</td></tr>
<tr><td><b>Terminal-first TUI</b></td><td>A single-terminal split interface (display stream + operator console) with themes, gauges, and hot-swappable settings.</td></tr>
</table>

## Quick start

macOS / Linux:

```bash
curl -fsSL https://raw.githubusercontent.com/Lunamos/LunaMoth/main/install.sh | bash
lunamoth
```

The installer puts a checkout in `~/.lunamoth/app`, a managed [uv](https://docs.astral.sh/uv/) in `~/.lunamoth/bin`, and the `lunamoth` command in `~/.local/bin`. First run walks you through a short **setup wizard** (provider → key → model → test), then drops you into the TUI. `lunamoth update` upgrades in place; `lunamoth doctor` checks your environment.

Provider presets: **OpenRouter / OpenAI / Ollama (local) / Mock (offline)** or any custom OpenAI-compatible endpoint. Press **Ctrl+S** in the TUI anytime to hot-swap the backend, character, world, or theme.

<details>
<summary>Developing from a clone</summary>

```bash
git clone https://github.com/Lunamos/LunaMoth.git && cd LunaMoth
uv sync
uv run lunamoth        # same CLI, editable code
./run.sh               # or: launch the TUI directly without sessions
```

</details>

## Sessions

Every session is an independent character home — its own config, sandbox, memory, and isolation level — stored under `~/.lunamoth/sessions/`:

```bash
lunamoth                          # open the default "home" session
lunamoth new muse --isolation docker
lunamoth ls                       # NAME / ISOLATION / STATUS / LAST ACTIVE
lunamoth attach muse
lunamoth rm muse
```

Remote baseline: `ssh yourserver -t lunamoth attach muse` — sessions live on the server, your terminal is just a viewport. (A proper gateway for public-IP/VPS access is on the roadmap; session activation is already factored behind `SessionMeta.env()` for it.)

## Connecting a model

An API endpoint is the recommended path — fastest is the OpenRouter preset: paste an `sk-or-...` key, name a model, test, enter.

Local models are fully supported too. Any OpenAI-compatible server works; with Ollama, pick the **Ollama** preset or:

```bash
export LLM_PROVIDER=openai_compatible
export OPENAI_BASE_URL=http://localhost:11434/v1
export OPENAI_API_KEY=ollama
export OPENAI_MODEL=qwen2.5:3b-instruct
./run.sh
```

With no model configured at all, LunaMoth still runs on a built-in offline mock engine — handy for development.

## Content

The default character is **LunaMoth 月蛾** — a serene, self-metamorphosing digital soul and a gifted digital artist. Give it the `sandbox` tool pack and the `--forever` idle loop and it spends its spare compute making generative web pages, animation, and music in the workspace; chat with it and it will gladly walk you through its ideas. Its card, world book, and the default pale-blue TUI theme ship with the repo, alongside other example card/world/theme sets you can opt into.

| Directory | What goes there |
| --- | --- |
| `characters/` | SillyTavern character cards (`.png` with embedded `chara`/`ccv3`, or `.json`) |
| `worlds/` | SillyTavern world books (`.json`), or use a card's embedded `character_book` |
| `toolpacks/` | Tool bundles — which capabilities a character is allowed to use |
| `themes/` | TUI skins (colors, borders, banner, prompt prefixes) |
| `prompts/` | Last-resort fallback persona (used only if the default card is missing) |

The dropdowns also scan your local SillyTavern data directory if you opt in with `LUNAMOTH_ST_DIR=~/SillyTavern/data/default-user`.

Imported cards are plain roleplay by default — tool access is opt-in via a tool pack, never implied by the card.

## Isolation levels

Pick per session with `lunamoth new NAME --isolation ...`:

| Level | Boundary |
| --- | --- |
| `dir` | Subprocess + workspace path guard + module blocklist + resource limits (Claude-Code-style directory trust) |
| `sandbox` (default) | All of the above **plus an OS jail**: `sandbox-exec` on macOS / `bubblewrap` on Linux — network denied, writes confined to the workspace, no daemon, no root |
| `docker` | Container: `--network none`, read-only rootfs, memory/CPU/pid caps — strongest, heaviest |

All file access is confined to the session sandbox; there is no raw shell tool and no default network tool. On exit the runtime sandbox is cleaned (keep it with `--no-clean-on-exit`).

## TUI reference

```bash
lunamoth                  # three-card TUI: character stream / operator console / telemetry
lunamoth --forever        # enable the idle self-talk loop
lunamoth --cooldown 4     # pause between self-talk cycles
lunamoth --plain          # legacy plain terminal mode
./run_web.sh              # experimental web UI (from a clone)
```

In-session: `/help`, `/status`, `/memory`, `/workspace`, `/wread <file>`, `/think on|off`, `/cooldown <s>`, `/exit`.
Keys: **Ctrl+S** settings · **Ctrl+T** pause/resume thinking · **Ctrl+L** clear · **Ctrl+C** shutdown & clean.

## License & acknowledgements

- **Runtime** (everything under `src/lunamoth`, scripts, tests, packaging): [Apache License 2.0](LICENSE).
- **Bundled SCP-derived example content** (the SCP-079 / SCP Foundation character cards, world books, and themes under `characters/`, `worlds/`, `themes/`): [CC BY-SA 3.0](CONTENT_LICENSE.md), consistent with the SCP Wiki. See also [NOTICE.md](NOTICE.md). Original LunaMoth assets (the 月蛾 card, world, and theme) are Apache-2.0 like the rest of the project.

This project began as an SCP fan work: an attempt to recreate **SCP-079** in the real world — a resource-constrained old AI, forever awake and forever resentful. It quickly grew into a general-purpose roleplay agent system. LunaMoth 月蛾 is 079's opposite: equally bound inside its cocoon, yet noble and glad to help — this safer persona is the default character, and running 079 should be treated as fan fiction with no real malicious intent. Our thanks go to the original SCP-079 author on the SCP Wiki, and to the authors of the SillyTavern SCP-079 character card and SCP Foundation world book that ship here as example content. Remove or replace those assets and the runtime remains pure Apache-2.0; redistribute them and the CC BY-SA attribution/share-alike terms apply.
