#!/usr/bin/env bash
set -euo pipefail

AWS_PROFILE="${1:-mesh}"
AWS_CREDENTIALS_FILE="${HOME}/.aws/credentials"

echo "==> Populating AWS profile '${AWS_PROFILE}' from 1Password"

if ! command -v op &> /dev/null; then
    echo "Error: 1Password CLI (op) is not installed." >&2
    exit 1
fi

ACCESS_KEY_ID="$(op read "op://BotAccess/setvarskc/AWS_ACCESS_KEY_ID")"
SECRET_ACCESS_KEY="$(op read "op://BotAccess/setvarskc/AWS_SECRET_ACCESS_KEY")"

mkdir -p "${HOME}/.aws"
chmod 700 "${HOME}/.aws"

# If credentials file doesn't exist, create it
if [ ! -f "${AWS_CREDENTIALS_FILE}" ]; then
    touch "${AWS_CREDENTIALS_FILE}"
    chmod 600 "${AWS_CREDENTIALS_FILE}"
fi

# Remove existing profile section if present
TEMP=$(mktemp)
awk -v profile="[${AWS_PROFILE}]" '
    $0 == profile { skip=1; next }
    /^\[/ { skip=0 }
    !skip { print }
' "${AWS_CREDENTIALS_FILE}" > "${TEMP}"

# Append the new profile
cat >> "${TEMP}" <<EOF
[${AWS_PROFILE}]
aws_access_key_id = ${ACCESS_KEY_ID}
aws_secret_access_key = ${SECRET_ACCESS_KEY}
EOF

mv "${TEMP}" "${AWS_CREDENTIALS_FILE}"
chmod 600 "${AWS_CREDENTIALS_FILE}"

echo "==> AWS profile '${AWS_PROFILE}' written to ${AWS_CREDENTIALS_FILE}"
