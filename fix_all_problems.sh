#!/bin/bash
# Fix all problems: login loop and duplicate program startup

echo "========================================"
echo "COMPREHENSIVE FIX FOR LOGIN AND STARTUP"
echo "========================================"
echo "This script fixes:"
echo "1. Login loop (password prompt loop)"
echo "2. Duplicate program startup"
echo ""

# First, fix login loop issue
echo "=== PART 1: FIX LOGIN LOOP ==="
echo ""

if [ -f /etc/lightdm/lightdm.conf ]; then
    echo "Found lightdm configuration, removing autologin settings..."
    sudo cp /etc/lightdm/lightdm.conf /etc/lightdm/lightdm.conf.bak
    sudo sed -i '/autologin-user/d' /etc/lightdm/lightdm.conf
    sudo sed -i '/autologin-user-timeout/d' /etc/lightdm/lightdm.conf
    echo "Autologin settings removed from lightdm.conf"
    echo "Backup saved as /etc/lightdm/lightdm.conf.bak"
fi

echo ""
echo "=== PART 2: STOP DUPLICATE PROGRAMS ==="
echo ""

# Stop all spectrometer processes
echo "Stopping all spectrometer processes..."
pkill -f "python3.*main\.py" 2>/dev/null && echo "? Stopped main program" || echo "? No main program running"
pkill -f "start_spectrometer" 2>/dev/null && echo "? Stopped startup scripts" || echo "? No startup scripts running"

# Stop systemd user service
echo ""
echo "Stopping systemd user service..."
systemctl --user stop spectrometer.service 2>/dev/null && echo "? Stopped systemd service" || echo "? Systemd service not running"
systemctl --user disable spectrometer.service 2>/dev/null && echo "? Disabled systemd service" || echo "? Systemd service not enabled"

echo ""
echo "=== PART 3: CLEANUP DUPLICATE STARTUP CONFIG ==="
echo ""

# Remove duplicate autostart entries
echo "Cleaning duplicate startup configurations..."
AUTOSTART_DIR="$HOME/.config/autostart"
if [ -d "$AUTOSTART_DIR" ]; then
    # Keep only one spectrometer.desktop file
    COUNT=$(ls "$AUTOSTART_DIR"/*spectrometer*.desktop 2>/dev/null | wc -l)
    if [ $COUNT -gt 1 ]; then
        echo "Found $COUNT spectrometer desktop files, keeping only one..."
        # Keep the newest one or spectrometer.desktop
        if [ -f "$AUTOSTART_DIR/spectrometer.desktop" ]; then
            rm -f "$AUTOSTART_DIR"/spectrometer_*.desktop 2>/dev/null
            rm -f "$AUTOSTART_DIR"/spectrometer-*.desktop 2>/dev/null
            echo "? Kept spectrometer.desktop, removed duplicates"
        else
            # Keep the first one and remove others
            KEEP_FILE=$(ls "$AUTOSTART_DIR"/*spectrometer*.desktop | head -1)
            rm -f "$AUTOSTART_DIR"/*spectrometer*.desktop 2>/dev/null
            mv "$KEEP_FILE" "$AUTOSTART_DIR/spectrometer.desktop"
            echo "? Consolidated to spectrometer.desktop"
        fi
    fi
fi

# Cleanup desktop shortcuts
echo ""
echo "Cleaning desktop shortcuts..."
if [ -f "$HOME/Desktop/spectrometer.desktop" ]; then
    # Remove duplicate desktop shortcuts
    rm -f "$HOME/Desktop/spectrometer_"*.desktop 2>/dev/null
    rm -f "$HOME/Desktop/spectrometer-"*.desktop 2>/dev/null
    rm -f "$HOME/Desktop/Spectrometer_"*.desktop 2>/dev/null
    echo "? Cleaned desktop shortcuts"
fi

echo ""
echo "=== PART 4: CREATE SINGLE STARTUP CONFIG ==="
echo ""

# Create a single, simple startup configuration
cd ~/user/daq_tablet 2>/dev/null || {
    echo "Cannot access ~/user/daq_tablet"
    echo "Please run this script from the correct directory"
    exit 1
}

echo "Creating single startup configuration..."
cat > "$HOME/.config/autostart/spectrometer.desktop" << 'EOF'
[Desktop Entry]
Name=Gamma-ray Spectrometer
Comment=Radiation Spectrometer Data Acquisition
Exec=/bin/bash -c "cd '/home/raysen/user/daq_tablet' && ./start_spectrometer_absolute.sh"
Icon=/home/raysen/user/daq_tablet/core/icons/icon.png
Terminal=false
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
EOF

chmod +x "$HOME/.config/autostart/spectrometer.desktop"
echo "? Created single autostart configuration"

echo ""
echo "=== PART 5: DISABLE SYSTEMD SERVICE ==="
echo ""

# Disable systemd service to prevent duplicate startup
SYSTEMD_FILE="$HOME/.config/systemd/user/spectrometer.service"
if [ -f "$SYSTEMD_FILE" ]; then
    echo "Disabling systemd service to prevent duplicates..."
    systemctl --user stop spectrometer.service 2>/dev/null
    systemctl --user disable spectrometer.service 2>/dev/null
    mv "$SYSTEMD_FILE" "$SYSTEMD_FILE.disabled"
    echo "? Systemd service disabled and moved to .disabled"
fi

echo ""
echo "=== PART 6: VERIFY FIX ==="
echo ""

echo "Current program instances:"
ps aux | grep -E "python3.*main\.py|start_spectrometer" | grep -v grep

echo ""
echo "Autostart configurations:"
ls -la "$HOME/.config/autostart/" 2>/dev/null || echo "No autostart directory"

echo ""
echo "Desktop shortcuts:"
ls -la "$HOME/Desktop/"*spectrometer* 2>/dev/null || echo "No desktop shortcuts"

echo ""
echo "=== PART 7: NEXT STEPS ==="
echo "========================================"
echo "FIXES APPLIED:"
echo "1. ? Removed problematic autologin configuration"
echo "2. ? Stopped duplicate program instances"
echo "3. ? Cleaned duplicate startup configurations"
echo "4. ? Created single autostart entry"
echo "5. ? Disabled systemd service (to prevent duplicates)"
echo ""
echo "NEXT STEPS:"
echo "1. RESTART THE SYSTEM:"
echo "   sudo reboot"
echo ""
echo "2. After restart:"
echo "   - Login with your password (autologin is disabled)"
echo "   - Only ONE program instance should start automatically"
echo ""
echo "3. If you still have login issues:"
echo "   - Press Ctrl+Alt+F3 to access terminal"
echo "   - Login with username/password"
echo "   - Run: rm ~/.local/share/keyrings/login.keyring"
echo "   - Run: sudo systemctl restart lightdm"
echo ""
echo "4. To re-enable autologin (after fixing login):"
echo "   sudo nano /etc/lightdm/lightdm.conf"
echo "   Add: autologin-user=raysen"
echo "        autologin-user-timeout=0"
echo "   sudo systemctl restart lightdm"
echo ""
echo "5. To manually start program:"
echo "   cd ~/user/daq_tablet"
echo "   ./start_spectrometer_absolute.sh"
echo "========================================"
