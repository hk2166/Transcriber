#!/usr/bin/env bash
#
# Launch Confab for local development: Ollama + backend + frontend.
# Backend and frontend run in the background, logging to .dev-logs/.
# Stop everything with ./kill.sh
#
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$ROOT/apps/backend"
FRONTEND="$ROOT/apps/desktop"
LOGDIR="$ROOT/.dev-logs"
mkdir -p "$LOGDIR"

port_busy() { lsof -nP -iTCP:"$1" -sTCP:LISTEN -t >/dev/null 2>&1; }

# ---- Ollama (for summaries + chat) -----------------------------------------
echo "→ Ollama…"
if curl -s --max-time 2 http://localhost:11434/api/tags >/dev/null 2>&1; then
  echo "  already running"
elif command -v ollama >/dev/null 2>&1; then
  nohup ollama serve >"$LOGDIR/ollama.log" 2>&1 &
  echo "  started (logs: .dev-logs/ollama.log)"
else
  echo "  ⚠ ollama not installed — summaries & chat will be unavailable"
fi

# ---- Backend (FastAPI, 127.0.0.1:8765) -------------------------------------
echo "→ Backend (127.0.0.1:8765)…"
if port_busy 8765; then
  echo "  ⚠ port 8765 already in use — run ./kill.sh first"
else
  ( cd "$BACKEND" && exec uv run uvicorn main:app --host 127.0.0.1 --port 8765 ) \
    >"$LOGDIR/backend.log" 2>&1 &
  for _ in $(seq 1 20); do
    curl -s --max-time 1 http://127.0.0.1:8765/health >/dev/null 2>&1 && break
    sleep 1
  done
  curl -s --max-time 1 http://127.0.0.1:8765/health >/dev/null 2>&1 \
    && echo "  ready (logs: .dev-logs/backend.log)" \
    || echo "  ⚠ not responding yet — check .dev-logs/backend.log"
fi

# ---- Frontend (Vite, http://localhost:1420) --------------------------------
echo "→ Frontend (http://localhost:1420)…"
if port_busy 1420; then
  echo "  ⚠ port 1420 already in use — run ./kill.sh first"
else
  ( cd "$FRONTEND" && exec npm run dev ) >"$LOGDIR/frontend.log" 2>&1 &
  echo "  starting (logs: .dev-logs/frontend.log)"
fi

echo ""
echo "Confab is up → open  http://localhost:1420"
echo "  logs:  tail -f .dev-logs/backend.log"
echo "  stop:  ./kill.sh"
