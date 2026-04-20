#!/bin/bash
set -e

SERVICE_NAME="insigne"
SERVICE_FILE="$HOME/.config/systemd/user/$SERVICE_NAME.service"

echo "Removing $SERVICE_NAME systemd user service..."

systemctl --user stop    "$SERVICE_NAME" 2>/dev/null || true
systemctl --user disable "$SERVICE_NAME" 2>/dev/null || true
rm -f "$SERVICE_FILE"
systemctl --user daemon-reload

echo "Done. Service removed."
