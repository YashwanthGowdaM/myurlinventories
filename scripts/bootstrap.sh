#!/usr/bin/env bash
# Idempotent VM preparation. Executed over SSH by the deploy workflow on every run.
set -euo pipefail

SUDO="sudo -n"
$SUDO true 2>/dev/null || { echo "ERROR: this user needs passwordless sudo"; exit 1; }

if ! command -v rsync >/dev/null || ! command -v crontab >/dev/null; then
  $SUDO apt-get update -qq
  $SUDO apt-get install -y -qq rsync cron
fi

if ! command -v docker >/dev/null; then
  echo "Installing Docker..."
  curl -fsSL https://get.docker.com | $SUDO sh
fi
if ! id -nG "$USER" | grep -qw docker; then
  $SUDO usermod -aG docker "$USER"   # takes effect for the next SSH session
fi

mkdir -p "$HOME/urls"

# Session-signing secret: created once, never overwritten, never leaves the VM.
if [ ! -s "$HOME/urls/.env" ]; then
  echo "Creating $HOME/urls/.env"
  ( umask 077; printf 'SECRET_KEY=%s\nCOOKIE_SECURE=1\n' "$(openssl rand -hex 32)" > "$HOME/urls/.env" )
fi

# Open web ports only if the OS firewall is already active (never enable it blindly).
if command -v ufw >/dev/null && $SUDO ufw status | grep -q "Status: active"; then
  for rule in 80/tcp 443/tcp 443/udp; do $SUDO ufw allow "$rule" >/dev/null; done
fi

# Port 80 may belong to an existing nginx. Leave it alone; just redirect our hostname to https.
if systemctl is-active --quiet nginx 2>/dev/null; then
  CONF=/etc/nginx/conf.d/urls-redirect.conf
  printf '%s\n' 'server {' '    listen 80;' '    listen [::]:80;' \
    '    server_name urls.yashwanthgowdam.in;' '    return 301 https://$host$request_uri;' '}' \
    | $SUDO tee "$CONF" >/dev/null
  if $SUDO nginx -t >/dev/null 2>&1; then
    $SUDO systemctl reload nginx
  else
    $SUDO rm -f "$CONF"
    echo "WARN: nginx config test failed; redirect not installed (site still works on https)."
  fi
fi

# Nightly database backup at 02:15.
LINE='15 2 * * * bash "$HOME/urls/scripts/backup.sh" >> "$HOME/urls-backup.log" 2>&1'
( crontab -l 2>/dev/null | grep -v 'urls/scripts/backup.sh' || true; echo "$LINE" ) | crontab -

echo "VM is ready."
