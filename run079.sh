#!/usr/bin/env bash
set -eo pipefail
cd "$(dirname "$0")"

usage() {
  cat <<'USAGE'
Open SCP 079 launcher

Default:
  ./run079.sh [--cooldown 0.5]
      Run the single-terminal split TUI.

Options:
  --cooldown <seconds>   Thought-loop pause, default 0.5
  --plain               Legacy plain terminal mode
  --no-think            Start with eternal thinking paused
  --no-clean-on-exit    Do not clean runtime sandbox on shutdown
  --help                Show this help

Examples:
  ./run079.sh
  ./run079.sh --cooldown 0.5
  ./run079.sh --plain --no-think
USAGE
}

MODE="tui"
COOLDOWN="0.5"
EXTRA=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --help|-h)
      usage
      exit 0
      ;;
    --plain|--single)
      MODE="plain"
      shift
      ;;
    --display)
      MODE="plain"
      EXTRA+=("--input-fifo" "sandbox/control/operator.in")
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
      COOLDOWN="$1"
      shift
      ;;
  esac
done

export LLM_PROVIDER="${LLM_PROVIDER:-openai_compatible}"
export OPENAI_BASE_URL="${OPENAI_BASE_URL:-http://localhost:11434/v1}"
export OPENAI_API_KEY="${OPENAI_API_KEY:-ollama}"
export OPENAI_MODEL="${OPENAI_MODEL:-hf.co/bartowski/Llama-3.2-3B-Instruct-uncensored-GGUF:Q4_K_M}"

run_python() {
  if command -v uv >/dev/null 2>&1; then
    exec uv run python "$@"
  else
    exec python3 "$@"
  fi
}

case "$MODE" in
  tui)
    run_python -m scp079.tui --cooldown "$COOLDOWN" "${EXTRA[@]}"
    ;;
  plain)
    run_python -m scp079.terminal --cooldown "$COOLDOWN" "${EXTRA[@]}"
    ;;
  control)
    run_python -m scp079.control "${EXTRA[@]}"
    ;;
esac
