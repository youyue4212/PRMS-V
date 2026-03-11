#!/bin/bash
# Setup USB auto-export (udev + systemd)
# Run as normal user (uses sudo internally)

set -euo pipefail

# Color codes
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

print_status() { echo -e "${GREEN}[+]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[!]${NC} $1"; }
print_error() { echo -e "${RED}[-]${NC} $1"; }

if [ "$EUID" -eq 0 ]; then
    print_error "Please do not run this script as root. Run as normal user."
    exit 1
fi

CURRENT_USER=$(whoami)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROGRAM_DIR="${PROGRAM_DIR:-$SCRIPT_DIR}"

print_status "Current user: $CURRENT_USER"
print_status "Program directory: $PROGRAM_DIR"

# Ensure required files exist
if [ ! -f "$PROGRAM_DIR/export_to_usb.sh" ]; then
    print_error "export_to_usb.sh not found in $PROGRAM_DIR"
    exit 1
fi
if [ ! -f "$PROGRAM_DIR/spectrometer-usb-export-wrapper.sh" ]; then
    print_error "spectrometer-usb-export-wrapper.sh not found in $PROGRAM_DIR"
    exit 1
fi
if [ ! -f "$PROGRAM_DIR/99-usb-export.rules" ]; then
    print_error "99-usb-export.rules not found in $PROGRAM_DIR"
    exit 1
fi

# Install system dependencies
print_status "Installing dependencies (rsync, udisks2)..."
sudo apt update
sudo apt install -y rsync udisks2

# Install scripts
print_status "Installing export scripts to /usr/local/bin..."
sudo cp "$PROGRAM_DIR/export_to_usb.sh" /usr/local/bin/export_to_usb.sh
sudo cp "$PROGRAM_DIR/spectrometer-usb-export-wrapper.sh" /usr/local/bin/spectrometer-usb-export-wrapper.sh
sudo chmod +x /usr/local/bin/export_to_usb.sh /usr/local/bin/spectrometer-usb-export-wrapper.sh

# Install udev rule
print_status "Installing udev rule..."
sudo cp "$PROGRAM_DIR/99-usb-export.rules" /etc/udev/rules.d/99-usb-export.rules

# Install systemd unit
print_status "Installing systemd template unit..."
sudo tee /etc/systemd/system/spectrometer-usb-export@.service > /dev/null << EOF
[Unit]
Description=Spectrometer USB export for %i
After=local-fs.target

[Service]
Type=oneshot
RemainAfterExit=no
TimeoutStartSec=240
Environment=HOME=/home/$CURRENT_USER
Environment=PROGRAM_DIR=$PROGRAM_DIR
Environment=EXPORT_SCRIPT=/usr/local/bin/export_to_usb.sh
ExecStart=/usr/local/bin/spectrometer-usb-export-wrapper.sh %i

[Install]
WantedBy=multi-user.target
EOF

# Reload and trigger
print_status "Reloading systemd and udev rules..."
sudo systemctl daemon-reload
sudo udevadm control --reload-rules
sudo udevadm trigger --action=add --subsystem-match=block

print_status "USB auto-export setup complete."
print_warning "Insert a USB drive and wait 1¨C2 minutes for export to finish."

# Auto-detect USB partition (first removable partition)
detect_usb_partition() {
    lsblk -nrpo NAME,TYPE,RM | awk '$2=="part" && $3=="1" {print $1; exit}'
}

# Optional test
echo ""
read -p "Do you want to run a test export now? (y/N): " run_test
if [[ "$run_test" == "y" || "$run_test" == "Y" ]]; then
    read -p "Enter device partition (e.g., sda1 or sdb1) [auto]: " dev_part
    if [ -z "$dev_part" ]; then
        auto_dev=$(detect_usb_partition)
        if [ -n "$auto_dev" ]; then
            dev_part="$(basename "$auto_dev")"
            print_status "Auto-detected partition: $dev_part"
        fi
    fi
    if [ -n "$dev_part" ]; then
        print_status "Starting test unit: spectrometer-usb-export@${dev_part}.service"
        sudo systemctl start "spectrometer-usb-export@${dev_part}.service" || true
        sudo systemctl status "spectrometer-usb-export@${dev_part}.service" --no-pager -l || true
        sudo journalctl -u "spectrometer-usb-export@${dev_part}.service" -n 80 --no-pager || true
    else
        print_warning "No USB partition detected; skipping test."
    fi
fi
