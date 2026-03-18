#!/usr/bin/env bash
set -euo pipefail

SYSTEMD_USER_DIR="${HOME}/.config/systemd/user"
HOSTS_FILE="${HOME}/.ssh/ecs_hosts"
SSH_CONFIG="${HOME}/.ssh/config"

echo "==> Removing SSH config sync from ECS instances"

# Stop and disable timer
if systemctl --user is-active --quiet sync-ssh-ecs.timer 2>/dev/null; then
    echo "==> Stopping timer"
    systemctl --user stop sync-ssh-ecs.timer
fi

if systemctl --user is-enabled --quiet sync-ssh-ecs.timer 2>/dev/null; then
    echo "==> Disabling timer"
    systemctl --user disable sync-ssh-ecs.timer
fi

# Remove symlinks
echo "==> Removing systemd unit symlinks"
rm -f "${SYSTEMD_USER_DIR}/sync-ssh-ecs.service"
rm -f "${SYSTEMD_USER_DIR}/sync-ssh-ecs.timer"

# Reload systemd
echo "==> Reloading systemd user daemon"
systemctl --user daemon-reload

# Remove Include line from SSH config
if [ -f "${SSH_CONFIG}" ] && grep -qF "Include ${HOSTS_FILE}" "${SSH_CONFIG}"; then
    echo "==> Removing Include directive from ${SSH_CONFIG}"
    TEMP=$(mktemp)
    grep -vF "Include ${HOSTS_FILE}" "${SSH_CONFIG}" > "${TEMP}"
    mv "${TEMP}" "${SSH_CONFIG}"
    chmod 600 "${SSH_CONFIG}"
fi

# Remove generated hosts file
if [ -f "${HOSTS_FILE}" ]; then
    echo "==> Removing ${HOSTS_FILE}"
    rm -f "${HOSTS_FILE}"
fi

echo ""
echo "==> Done! SSH config sync has been removed."
echo "    Note: The AWS profile 'mesh' in ~/.aws/credentials was left in place."
echo "    Remove it manually if no longer needed."
