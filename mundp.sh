#!/usr/bin/env bash
# MUNDP portal control script. Start, stop, restart, or check the server.
#
# Usage:
#   ./mundp.sh start         # launch on http://127.0.0.1:5055 (localhost only)
#   ./mundp.sh stop          # stop a running server
#   ./mundp.sh restart       # stop then start
#   ./mundp.sh status        # is it running?
#   ./mundp.sh open          # open http://127.0.0.1:5055 in your browser
#   ./mundp.sh logs          # tail the server log
#
# Environment overrides (optional):
#   PORT=5000 ./mundp.sh start
#   HOST=0.0.0.0 ./mundp.sh start    # bind to LAN — also set ALLOWED_IP_PREFIXES in .env
set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PROJECT_DIR}/.venv/bin/python"
PORT="${PORT:-5055}"
HOST="${HOST:-127.0.0.1}"
PID_FILE="${PROJECT_DIR}/.mundp.pid"
LOG_FILE="${PROJECT_DIR}/.mundp.log"

cmd="${1:-status}"

is_running() {
    if [[ ! -f "$PID_FILE" ]]; then return 1; fi
    local pid
    pid="$(cat "$PID_FILE" 2>/dev/null || true)"
    [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

start_server() {
    if is_running; then
        echo "Already running (PID $(cat "$PID_FILE")). URL: http://${HOST}:${PORT}"
        return 0
    fi
    # Free the port if some orphan still owns it.
    local in_use
    in_use="$(lsof -ti tcp:"$PORT" 2>/dev/null || true)"
    if [[ -n "$in_use" ]]; then
        echo "Port $PORT is in use by PID $in_use; killing it."
        kill -9 $in_use 2>/dev/null || true
        sleep 1
    fi
    if [[ ! -x "$PYTHON" ]]; then
        echo "Python venv not found at $PYTHON. Run:"
        echo "  cd \"$PROJECT_DIR\" && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
        exit 1
    fi
    cd "$PROJECT_DIR"
    HOST="$HOST" PORT="$PORT" nohup "$PYTHON" app.py > "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    sleep 1
    if is_running; then
        echo "Started (PID $(cat "$PID_FILE"))."
        echo "  URL:  http://${HOST}:${PORT}"
        echo "  Logs: $LOG_FILE"
    else
        echo "Failed to start. Last lines of log:"
        tail -n 20 "$LOG_FILE" 2>/dev/null || true
        exit 1
    fi
}

stop_server() {
    if ! is_running; then
        echo "Not running."
        # Tidy up any orphan on this port just in case.
        local in_use
        in_use="$(lsof -ti tcp:"$PORT" 2>/dev/null || true)"
        if [[ -n "$in_use" ]]; then
            echo "Killing orphan PID(s) on port $PORT: $in_use"
            kill -9 $in_use 2>/dev/null || true
        fi
        rm -f "$PID_FILE"
        return 0
    fi
    local pid
    pid="$(cat "$PID_FILE")"
    kill "$pid" 2>/dev/null || true
    sleep 1
    if kill -0 "$pid" 2>/dev/null; then
        kill -9 "$pid" 2>/dev/null || true
    fi
    rm -f "$PID_FILE"
    echo "Stopped."
}

status_server() {
    if is_running; then
        echo "Running (PID $(cat "$PID_FILE"))."
        echo "  URL:  http://${HOST}:${PORT}"
        echo "  Logs: $LOG_FILE"
    else
        echo "Not running."
    fi
}

open_browser() {
    if ! is_running; then start_server; fi
    open "http://${HOST}:${PORT}/"
}

case "$cmd" in
    start)   start_server ;;
    stop)    stop_server ;;
    restart) stop_server; start_server ;;
    status)  status_server ;;
    open)    open_browser ;;
    logs)    tail -f "$LOG_FILE" ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|open|logs}"
        exit 2
        ;;
esac
