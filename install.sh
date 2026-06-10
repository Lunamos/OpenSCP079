#!/usr/bin/env bash
# LunaMoth installer (macOS / Linux).
#
#   curl -fsSL https://raw.githubusercontent.com/Lunamos/LunaMoth/main/install.sh | bash
#
# Hermes-style layout: the code lives as a git checkout in $LUNAMOTH_HOME/app,
# a managed uv lives in $LUNAMOTH_HOME/bin, and a small shim is linked into
# ~/.local/bin/lunamoth. Updating later = `lunamoth update` (git pull + uv sync).
set -euo pipefail

REPO_URL="${LUNAMOTH_REPO:-https://github.com/Lunamos/LunaMoth.git}"
LUNAMOTH_HOME="${LUNAMOTH_HOME:-$HOME/.lunamoth}"
APP_DIR="$LUNAMOTH_HOME/app"
BIN_DIR="$LUNAMOTH_HOME/bin"
LINK_DIR="${LUNAMOTH_LINK_DIR:-$HOME/.local/bin}"

say()  { printf '\033[1;36m[lunamoth]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[lunamoth]\033[0m %s\n' "$*" >&2; exit 1; }

case "$(uname -s)" in
  Darwin|Linux) ;;
  *) fail "unsupported platform $(uname -s) (macOS and Linux only for now)" ;;
esac
command -v git >/dev/null 2>&1 || fail "git is required (macOS: xcode-select --install; Linux: apt/dnf install git)"

mkdir -p "$LUNAMOTH_HOME" "$BIN_DIR" "$LINK_DIR"

# --- uv: prefer system uv, else install a managed copy into $BIN_DIR --------
UV="$(command -v uv || true)"
if [ -z "$UV" ]; then
  if [ ! -x "$BIN_DIR/uv" ]; then
    say "installing uv into $BIN_DIR ..."
    installer="$(mktemp)"
    curl -fsSL https://astral.sh/uv/install.sh -o "$installer" || fail "could not download uv installer"
    UV_UNMANAGED_INSTALL="$BIN_DIR" sh "$installer" >/dev/null || fail "uv install failed"
    rm -f "$installer"
  fi
  UV="$BIN_DIR/uv"
fi
say "using uv: $UV"

# --- code: clone or fast-forward $APP_DIR -----------------------------------
if [ -d "$APP_DIR/.git" ]; then
  say "updating existing checkout at $APP_DIR ..."
  git -C "$APP_DIR" pull --ff-only origin main || fail "git pull failed (local changes? see $APP_DIR)"
else
  say "cloning $REPO_URL -> $APP_DIR ..."
  git clone --depth 1 "$REPO_URL" "$APP_DIR"
fi

say "syncing python environment ..."
(cd "$APP_DIR" && "$UV" sync -q) || fail "uv sync failed"

# --- shim --------------------------------------------------------------------
SHIM="$LINK_DIR/lunamoth"
cat > "$SHIM" <<EOF
#!/usr/bin/env bash
exec "$APP_DIR/.venv/bin/lunamoth" "\$@"
EOF
chmod +x "$SHIM"
say "installed shim: $SHIM"

case ":$PATH:" in
  *":$LINK_DIR:"*) ;;
  *) say "NOTE: $LINK_DIR is not on your PATH. Add this to your shell profile:"
     say "  export PATH=\"$LINK_DIR:\$PATH\"" ;;
esac

say "done. run: lunamoth"
