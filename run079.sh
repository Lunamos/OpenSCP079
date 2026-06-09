#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

usage() {
  cat <<'USAGE'
Open SCP 079 launcher

Default:
  ./run079.sh [cooldown]
      Open a new SCP-079 display terminal and use the current terminal as
      the operator control console.

Options:
  --cooldown <seconds>   Thought-loop pause, default 0.5
  --single              Run display + input in this terminal for debugging
  --display             Internal: run the display terminal
  --control             Internal: run the operator console
  --help                Show this help

Examples:
  ./run079.sh
  ./run079.sh 0.5
  ./run079.sh --cooldown 10
  ./run079.sh --single
USAGE
}

MODE="launch"
COOLDOWN="0.5"
EXTRA=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --help|-h)
      usage
      exit 0
      ;;
    --single)
      MODE="single"
      shift
      ;;
    --display)
      MODE="display"
      shift
      ;;
    --control)
      MODE="control"
      shift
      ;;
    --cooldown)
      COOLDOWN="${2:-0.5}"
      shift 2
      ;;
    --cooldown=*)
      COOLDOWN="${1#--cooldown=}"
      shift
      ;;
    --*)
      EXTRA+=("$1")
      shift
      ;;
    *)
      # Backward-compatible: ./run079.sh 0.5
      COOLDOWN="$1"
      shift
      ;;
  esac
done

export LLM_PROVIDER="${LLM_PROVIDER:-openai_compatible}"
export OPENAI_BASE_URL="${OPENAI_BASE_URL:-http://localhost:11434/v1}"
export OPENAI_API_KEY="${OPENAI_API_KEY:-ollama}"
export OPENAI_MODEL="${OPENAI_MODEL:-hf.co/bartowski/Llama-3.2-3B-Instruct-uncensored-GGUF:Q4_K_M}"

py_run() {
  if command -v uv >/dev/null 2>&1; then
    uv run python "$@"
  else
    python3 "$@"
  fi
}

case "$MODE" in
  single)
    exec bash -c 'if command -v uv >/dev/null 2>&1; then exec uv run python -m scp079.terminal --cooldown "$0" "${@:1}"; else exec python3 -m scp079.terminal --cooldown "$0" "${@:1}"; fi' "$COOLDOWN" "${EXTRA[@]}"
    ;;
  display)
    mkdir -p sandbox/control
    exec bash -c 'if command -v uv >/dev/null 2>&1; then exec uv run python -m scp079.terminal --input-fifo sandbox/control/operator.in --cooldown "$0" "${@:1}"; else exec python3 -m scp079.terminal --input-fifo sandbox/control/operator.in --cooldown "$0" "${@:1}"; fi' "$COOLDOWN" "${EXTRA[@]}"
    ;;
  control)
    exec bash -c 'if command -v uv >/dev/null 2>&1; then exec uv run python -m scp079.control "${@:0}"; else exec python3 -m scp079.control "${@:0}"; fi' "${EXTRA[@]}"
    ;;
  launch)
    mkdir -p sandbox/control
    PROJECT_DIR="$(pwd)"
    DISPLAY_CMD="cd \"$PROJECT_DIR\" && ./run079.sh --display --cooldown \"$COOLDOWN\""
    if command -v osascript >/dev/null 2>&1; then
      ESCAPED_DISPLAY_CMD=$(printf '%s' "$DISPLAY_CMD" | sed 's/\\/\\\\/g; s/"/\\"/g')
      osascript -e "tell application \"Terminal\" to do script \"$ESCAPED_DISPLAY_CMD\"" >/dev/null
      echo "Opened SCP-079 display terminal with cooldown=${COOLDOWN}s"
      echo "Current terminal is the operator control console."
      echo "Use /help in the console. Use /exit079 to shut down the display."
      sleep 0.7
      exec ./run079.sh --control
    else
      echo "Could not auto-open a second terminal. Run these manually:" >&2
      echo "  Terminal A: ./run079.sh --display --cooldown $COOLDOWN" >&2
      echo "  Terminal B: ./run079.sh --control" >&2
      exit 1
    fi
    ;;
esac
