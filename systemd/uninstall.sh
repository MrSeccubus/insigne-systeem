#!/bin/bash
set -e

# Required for systemctl --user to work in non-login shells (e.g. SSH)
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=/run/user/$(id -u)/bus}"

SERVICE_NAME="insigne"
SERVICE_FILE="$HOME/.config/systemd/user/$SERVICE_NAME.service"

echo "Removing $SERVICE_NAME systemd user service..."

systemctl --user stop    "$SERVICE_NAME" 2>/dev/null || true
systemctl --user disable "$SERVICE_NAME" 2>/dev/null || true
rm -f "$SERVICE_FILE"
systemctl --user daemon-reload

echo "Done. Service removed."
