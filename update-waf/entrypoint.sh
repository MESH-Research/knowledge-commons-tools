#!/bin/sh
# Container entrypoint: register this container's egress IP with the WAFv2
# IPSet on startup, hand control to the real command, and on SIGTERM/SIGINT
# (ECS clean shutdown) remove this container's IP before exiting.
#
# Env vars consumed by update_waf_ip.py:
#   WAF_IP_SET_NAME, WAF_IP_SET_ID  (required)
#   WAF_IP_SET_SCOPE                (optional, defaults to REGIONAL)
#   AWS_REGION                      (required for REGIONAL)
#   IP_CHECK_URL                    (optional)
#
# AWS credentials come from the standard boto3 chain (ECS task role,
# instance profile, AWS_ACCESS_KEY_ID/SECRET, ...).
set -u

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

uv run --script "${SCRIPT_DIR}/update_waf_ip.py"

APP_PID=""
SHUTTING_DOWN=0

on_signal() {
    SHUTTING_DOWN=1
    if [ -n "$APP_PID" ]; then
        kill -TERM "$APP_PID" 2>/dev/null || true
    fi
}

trap on_signal TERM INT

"$@" &
APP_PID=$!

# wait may be interrupted by a trap; loop until the child has actually exited.
wait "$APP_PID" 2>/dev/null
EXIT_CODE=$?
while kill -0 "$APP_PID" 2>/dev/null; do
    wait "$APP_PID" 2>/dev/null
    EXIT_CODE=$?
done

# Only remove this container's IP on signal-initiated shutdown. Crashes and
# app-initiated exits leave the IP in place for debugging / reconciliation.
if [ "$SHUTTING_DOWN" -eq 1 ]; then
    uv run --script "${SCRIPT_DIR}/update_waf_ip.py" --remove || true
fi

exit "$EXIT_CODE"
