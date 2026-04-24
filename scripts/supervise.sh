#!/usr/bin/env bash
# Supervisor: restart the agent indefinitely with a sleep between invocations.
# Kill the shell process group or `pkill -f "broker launch"` to stop.

set -u

AGENT_NAME="${AGENT_NAME:-broker}"
SESSION_TIMEOUT="${SESSION_TIMEOUT_S:-900}"
LOG_FILE="agent_${AGENT_NAME}.log"

cd "$(dirname "$0")/.."

echo "[supervise] agent=${AGENT_NAME} timeout=${SESSION_TIMEOUT}s log=${LOG_FILE}"

while true; do
    .venv/bin/broker launch --name "${AGENT_NAME}" --session-timeout "${SESSION_TIMEOUT}" 2>&1 | tee -a "${LOG_FILE}"
    ec=${PIPESTATUS[0]}
    echo "[supervise] agent exited (${ec}), restarting in 5s..." | tee -a "${LOG_FILE}"
    sleep 5
done
