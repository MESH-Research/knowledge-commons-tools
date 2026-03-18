#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYSTEMD_USER_DIR="${HOME}/.config/systemd/user"
SSH_DIR="${HOME}/.ssh"
HOSTS_FILE="${SSH_DIR}/ecs_hosts"
SSH_CONFIG="${SSH_DIR}/config"
AWS_PROFILE="mesh"

echo "==> Setting up SSH config sync from ECS instances"

# Populate AWS profile from 1Password
echo "==> Setting up AWS profile '${AWS_PROFILE}'"
"${SCRIPT_DIR}/setup_aws_profile.sh" "${AWS_PROFILE}"

# Generate systemd unit files with absolute paths
echo "==> Generating systemd unit files"

cat > "${SCRIPT_DIR}/systemd/sync-ssh-ecs.service" <<EOF
[Unit]
Description=Sync ECS instance IPs to SSH config

[Service]
Type=oneshot
WorkingDirectory=${SCRIPT_DIR}
ExecStart=$(command -v uv) run ${SCRIPT_DIR}/sync_ssh.py --profile ${AWS_PROFILE}
EOF

cat > "${SCRIPT_DIR}/systemd/sync-ssh-ecs.timer" <<EOF
[Unit]
Description=Periodically sync ECS SSH config

[Timer]
OnBootSec=1min
OnUnitActiveSec=15min

[Install]
WantedBy=timers.target
EOF

# Create systemd user directory
mkdir -p "${SYSTEMD_USER_DIR}"

# Symlink units
echo "==> Symlinking systemd units"
ln -sf "${SCRIPT_DIR}/systemd/sync-ssh-ecs.service" "${SYSTEMD_USER_DIR}/sync-ssh-ecs.service"
ln -sf "${SCRIPT_DIR}/systemd/sync-ssh-ecs.timer" "${SYSTEMD_USER_DIR}/sync-ssh-ecs.timer"

# Reload systemd
echo "==> Reloading systemd user daemon"
systemctl --user daemon-reload

# Enable and start timer
echo "==> Enabling and starting timer"
systemctl --user enable --now sync-ssh-ecs.timer

# Ensure SSH directory and hosts file exist
mkdir -p "${SSH_DIR}"
chmod 700 "${SSH_DIR}"
touch "${HOSTS_FILE}"

# Ensure Include directive is in SSH config
if [ ! -f "${SSH_CONFIG}" ]; then
    echo "Include ${HOSTS_FILE}" > "${SSH_CONFIG}"
    chmod 600 "${SSH_CONFIG}"
elif ! grep -qF "Include ${HOSTS_FILE}" "${SSH_CONFIG}"; then
    TEMP=$(mktemp)
    echo "Include ${HOSTS_FILE}" > "${TEMP}"
    cat "${SSH_CONFIG}" >> "${TEMP}"
    mv "${TEMP}" "${SSH_CONFIG}"
    chmod 600 "${SSH_CONFIG}"
fi

# Run initial sync
echo "==> Running initial sync"
uv run "${SCRIPT_DIR}/sync_ssh.py" --profile "${AWS_PROFILE}" || echo "    Initial sync failed. Check AWS credentials with: aws sts get-caller-identity --profile ${AWS_PROFILE}"

echo ""
echo "==> Done! Timer status:"
systemctl --user status sync-ssh-ecs.timer --no-pager || true
