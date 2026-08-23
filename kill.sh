#!/usr/bin/env bash
#
# Stop Confab local dev: frontend (1420) + backend (8765).
# Ollama is left running (it's a shared service). Pass --ollama to stop it too.
#
set -uo pipefail

stop_port() {
  local port="$1" name="$2"
  local pids
  pids="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null || true)"
  if [ -n "$pids" ]; then
    kill $pids 2>/dev/null || true
    echo "  $name (port $port): stopped $pids"
  else
    echo "  $name (port $port): not running"
  fi
}

echo "→ Stopping Confab…"
stop_port 1420 "frontend"
stop_port 8765 "backend"
pkill -f "uvicorn main:app" 2>/dev/null || true

sleep 1
# Force-kill any survivors still holding the ports.
for port in 1420 8765; do
  pids="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null || true)"
  [ -n "$pids" ] && { kill -9 $pids 2>/dev/null || true; echo "  force-killed port $port ($pids)"; }
done

if [ "${1:-}" = "--ollama" ]; then
  pkill -f "ollama serve" 2>/dev/null && echo "  ollama: stopped" || echo "  ollama: not running"
else
  echo "  ollama: left running (use ./kill.sh --ollama to stop it too)"
fi

echo "Done."
