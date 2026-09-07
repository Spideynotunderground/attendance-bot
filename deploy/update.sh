#!/usr/bin/env bash
# Pull the latest code and restart. Attendance data is untouched.
set -euo pipefail
APP_DIR=/opt/attendance-bot

sudo git -C "$APP_DIR" fetch --quiet origin
sudo git -C "$APP_DIR" reset --hard --quiet origin/main
sudo "$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"
sudo systemctl restart attendance-bot
sleep 3
sudo systemctl status attendance-bot --no-pager --lines=10
