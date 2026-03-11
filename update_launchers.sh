#!/bin/bash
# One-click update for desktop launcher, autostart, and systemd service
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DESKTOP_SRC="$SCRIPT_DIR/spectrometer.desktop"
SERVICE_SRC="$SCRIPT_DIR/spectrometer.service"

if [ ! -f "$DESKTOP_SRC" ]; then
  echo "ERROR: Missing $DESKTOP_SRC"
  exit 1
fi

mkdir -p "$HOME/.local/share/applications" "$HOME/.config/autostart" "$HOME/Desktop"

# Update desktop launchers
install -m 644 "$DESKTOP_SRC" "$HOME/.local/share/applications/spectrometer.desktop"
install -m 644 "$DESKTOP_SRC" "$HOME/.config/autostart/spectrometer.desktop"
install -m 755 "$DESKTOP_SRC" "$HOME/Desktop/spectrometer.desktop" || true

RESTART_SERVICE=1
START_APP=0

for arg in "$@"; do
  case "$arg" in
    --no-restart)
      RESTART_SERVICE=0
      ;;
    --start-app)
      START_APP=1
      ;;
  esac
done

# Update systemd service (requires sudo)
if [ -f "$SERVICE_SRC" ]; then
  sudo cp "$SERVICE_SRC" /etc/systemd/system/spectrometer.service
  sudo systemctl daemon-reload
  sudo systemctl enable spectrometer.service
  if [ "$RESTART_SERVICE" -eq 1 ]; then
    sudo systemctl restart spectrometer.service || true
    echo "Systemd service updated and restarted."
  else
    echo "Systemd service updated (restart skipped)."
  fi
else
  echo "WARNING: Missing $SERVICE_SRC, skipped systemd update."
fi

if [ "$START_APP" -eq 1 ]; then
  if [ -x "$SCRIPT_DIR/start_spectrometer_absolute.sh" ]; then
    "$SCRIPT_DIR/start_spectrometer_absolute.sh" &
    echo "App started."
  else
    echo "WARNING: start_spectrometer_absolute.sh not found or not executable."
  fi
fi

echo "Launchers updated."
