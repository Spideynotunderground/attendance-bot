#!/usr/bin/env bash
# One-time setup on a fresh Ubuntu/Debian VM. Safe to re-run.
#
#   curl -fsSL https://raw.githubusercontent.com/Spideynotunderground/attendance-bot/main/deploy/setup.sh | bash
#
set -euo pipefail

REPO="${REPO:-https://github.com/Spideynotunderground/attendance-bot.git}"
APP_DIR=/opt/attendance-bot
DATA_DIR=/var/lib/attendance-bot
ENV_FILE=/etc/attendance-bot.env

echo "==> Installing packages"
sudo apt-get update -qq
sudo apt-get install -y -qq python3-venv python3-pip git tzdata fonts-dejavu-core

echo "==> Creating the service user"
id -u attbot >/dev/null 2>&1 || sudo useradd --system --home "$DATA_DIR" --shell /usr/sbin/nologin attbot

echo "==> Fetching the code"
if [ -d "$APP_DIR/.git" ]; then
  sudo git -C "$APP_DIR" fetch --quiet origin
  sudo git -C "$APP_DIR" reset --hard --quiet origin/main
else
  sudo git clone --quiet "$REPO" "$APP_DIR"
fi

echo "==> Installing dependencies"
sudo python3 -m venv "$APP_DIR/.venv"
sudo "$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip
sudo "$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

echo "==> Preparing the data directory"
sudo mkdir -p "$DATA_DIR"
sudo touch "$DATA_DIR/access_codes.txt"
sudo chown -R attbot:attbot "$DATA_DIR"
sudo chmod 700 "$DATA_DIR"

if [ ! -f "$ENV_FILE" ]; then
  echo "==> Creating $ENV_FILE"
  printf 'BOT_TOKEN=\nDATA_DIR=%s\n' "$DATA_DIR" | sudo tee "$ENV_FILE" >/dev/null
  sudo chmod 600 "$ENV_FILE"
fi

echo "==> Installing the service"
sudo cp "$APP_DIR/deploy/attendance-bot.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --quiet attendance-bot

if grep -q '^BOT_TOKEN=$' "$ENV_FILE"; then
  cat <<MSG

  Setup done, but the bot has no token yet.

    sudo nano $ENV_FILE        # paste your token after BOT_TOKEN=
    sudo systemctl start attendance-bot
    sudo journalctl -u attendance-bot -f

MSG
else
  sudo systemctl restart attendance-bot
  echo
  echo "  Running. Follow the log with:  sudo journalctl -u attendance-bot -f"
  echo
fi
