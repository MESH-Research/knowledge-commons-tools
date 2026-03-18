#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

op run --env-file="${SCRIPT_DIR}/.env.tpl" -- uv run "${SCRIPT_DIR}/sync_ssh.py" "$@"
