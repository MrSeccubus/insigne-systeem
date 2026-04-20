#!/bin/bash
set -e

# Required for systemctl --user to work in non-login shells (e.g. SSH)
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=/run/user/$(id -u)/bus}"

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_NAME="insigne"
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
SERVICE_FILE="$SYSTEMD_USER_DIR/$SERVICE_NAME.service"

echo "Installing $SERVICE_NAME as a systemd user service..."
echo "Install directory: $INSTALL_DIR"

# Verify run_prod.sh exists and is executable
if [ ! -f "$INSTALL_DIR/run_prod.sh" ]; then
    echo "ERROR: $INSTALL_DIR/run_prod.sh not found." >&2
    exit 1
fi
chmod +x "$INSTALL_DIR/run_prod.sh"

# Verify config.yml exists
if [ ! -f "$INSTALL_DIR/config.yml" ]; then
    echo "ERROR: $INSTALL_DIR/config.yml not found." >&2
    echo "Create it before installing — see CLAUDE.md for the required format." >&2
    exit 1
fi

# Create systemd user directory if it doesn't exist
mkdir -p "$SYSTEMD_USER_DIR"

# Generate service file from template, substituting the actual install path
sed "s|__INSTALL_DIR__|${INSTALL_DIR}|g" \
    "$INSTALL_DIR/systemd/insigne.service" \
    > "$SERVICE_FILE"

echo "Service file written to $SERVICE_FILE"

# Enable lingering so user services survive logout and start at boot
if ! loginctl show-user "$USER" 2>/dev/null | grep -q "^Linger=yes"; then
    echo "Enabling lingering for user $USER (required for start-at-boot)..."
    loginctl enable-linger "$USER"
fi

systemctl --user daemon-reload
systemctl --user enable "$SERVICE_NAME"
systemctl --user start "$SERVICE_NAME"

echo ""
echo "Done. Service is enabled and running."
echo "  Status : $(dirname "$0")/../insigne-ctl status"
echo "  Logs   : $(dirname "$0")/../insigne-ctl logs -f"
