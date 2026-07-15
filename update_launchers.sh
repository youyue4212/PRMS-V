#!/bin/bash
# One-click update for desktop launcher and per-user autostart.
# NOTE: This script deliberately does NOT install a system-wide systemd service.
# The app is autostarted via the per-user autostart entry only (see below).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DESKTOP_SRC="$SCRIPT_DIR/spectrometer.desktop"

if [ ! -f "$DESKTOP_SRC" ]; then
  echo "ERROR: Missing $DESKTOP_SRC"
  exit 1
fi

mkdir -p "$HOME/.local/share/applications" "$HOME/.config/autostart" "$HOME/Desktop"

# Update desktop launchers
install -m 644 "$DESKTOP_SRC" "$HOME/.local/share/applications/spectrometer.desktop"
install -m 644 "$DESKTOP_SRC" "$HOME/.config/autostart/spectrometer.desktop"
install -m 755 "$DESKTOP_SRC" "$HOME/Desktop/spectrometer.desktop" || true

START_APP=0

for arg in "$@"; do
  case "$arg" in
    --start-app)
      START_APP=1
      ;;
  esac
done

# Do NOT install/enable a system-wide systemd service.
# A system service starts before the graphical session and runs an invisible copy
# of the GUI on the wrong display; it also grabs the single-instance lock and stops
# the in-session autostart copy from showing. The app is launched only via the
# per-user autostart entry installed above (~/.config/autostart/spectrometer.desktop).
#
# Self-healing: if a legacy system service is still installed on this machine
# (from older versions of this script), disable and remove it so the problem
# does not recur.
if systemctl list-unit-files 2>/dev/null | grep -q '^spectrometer\.service'; then
  echo "Found legacy system service spectrometer.service; disabling and removing it..."
  sudo systemctl disable --now spectrometer.service || true
  sudo rm -f /etc/systemd/system/spectrometer.service
  sudo systemctl daemon-reload || true
  echo "Legacy system service removed."
else
  echo "No legacy system service found (good)."
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
