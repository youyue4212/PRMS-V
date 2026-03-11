#!/bin/bash
# Gamma-ray Spectrometer Installation Script
# Based on the comprehensive solution developed during troubleshooting

echo "========================================"
echo "GAMMA-RAY SPECTROMETER INSTALLATION"
echo "========================================"
echo "This script installs and configures the spectrometer software"
echo "on a fresh Ubuntu system (including Raspberry Pi)."
echo ""

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${GREEN}[?]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[!]${NC} $1"
}

print_error() {
    echo -e "${RED}[?]${NC} $1"
}

# Check if running as root
if [ "$EUID" -eq 0 ]; then
    print_error "Please do not run this script as root. Run as normal user."
    exit 1
fi

CURRENT_USER=$(whoami)
print_status "Current user: $CURRENT_USER"

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
print_status "Script directory: $SCRIPT_DIR"

echo ""
echo "=== STEP 1: INSTALL SYSTEM DEPENDENCIES ==="
echo ""

# Update package list
print_status "Updating package list..."
sudo apt update

# Install system dependencies
print_status "Installing system dependencies..."
sudo apt install -y \
    python3 \
    python3-pip \
    python3-venv \
    python3-pyqt5 \
    python3-serial \
    python3-pyqt5.qtsvg \
    onboard \
    lightdm \
    x11-xserver-utils \
    xserver-xorg-input-all \
    rsync \
    udisks2

# Install additional Python system packages
sudo apt install -y \
    python3-numpy \
    python3-pandas \
    python3-matplotlib

echo ""
echo "=== STEP 2: CREATE VIRTUAL ENVIRONMENT ==="
echo ""

# Ask user for virtual environment name
read -p "Enter virtual environment name [spectrometer_env]: " venv_name
VENV_NAME="${venv_name:-spectrometer_env}"
VENV_PATH="$HOME/$VENV_NAME"

print_status "Virtual environment will be created at: $VENV_PATH"

if [ -d "$VENV_PATH" ]; then
    print_warning "Virtual environment already exists at $VENV_PATH"
    read -p "Do you want to recreate it? (y/N): " recreate_venv
    if [[ "$recreate_venv" == "y" || "$recreate_venv" == "Y" ]]; then
        rm -rf "$VENV_PATH"
        python3 -m venv "$VENV_PATH"
        print_status "Virtual environment recreated at $VENV_PATH"
    else
        print_status "Using existing virtual environment"
    fi
else
    python3 -m venv "$VENV_PATH"
    print_status "Virtual environment created at $VENV_PATH"
fi

# Activate virtual environment and install Python packages
print_status "Installing Python packages in virtual environment..."
source "$VENV_PATH/bin/activate"

# Check if requirements.txt exists in script directory
if [ -f "$SCRIPT_DIR/requirements.txt" ]; then
    pip install -r "$SCRIPT_DIR/requirements.txt"
elif [ -f "requirements.txt" ]; then
    pip install -r requirements.txt
else
    # Install essential packages
    pip install pyqtgraph pyserial numpy pandas matplotlib scipy
    print_warning "No requirements.txt found, installed basic packages"
fi

# Verify installation
print_status "Verifying Python package installation..."
if python3 -c "import PyQt5, pyqtgraph, serial, numpy, pandas"; then
    print_status "All Python packages installed successfully"
else
    print_error "Failed to install some Python packages"
    exit 1
fi

deactivate

echo ""
echo "=== STEP 3: SETUP PROGRAM DIRECTORY ==="
echo ""

# Determine where to install the program
DEFAULT_INSTALL_DIR="$HOME/user/daq_tablet"
print_status "Default installation directory: $DEFAULT_INSTALL_DIR"

# Check if program files are already in the script directory
if [ -f "$SCRIPT_DIR/main.py" ]; then
    print_status "Found program files in script directory"
    PROGRAM_DIR="$SCRIPT_DIR"
else
    # Ask user for installation directory
    read -p "Enter installation directory [$DEFAULT_INSTALL_DIR]: " install_dir
    PROGRAM_DIR="${install_dir:-$DEFAULT_INSTALL_DIR}"
    
    # Create directory if it doesn't exist
    mkdir -p "$PROGRAM_DIR"
    
    # Copy files if script directory has them
    if [ "$SCRIPT_DIR" != "$PROGRAM_DIR" ]; then
        print_status "Copying program files to $PROGRAM_DIR"
        cp -r "$SCRIPT_DIR"/* "$PROGRAM_DIR"/ 2>/dev/null || true
    fi
fi

# Ensure we have the main.py file
if [ ! -f "$PROGRAM_DIR/main.py" ]; then
    print_error "main.py not found in $PROGRAM_DIR"
    print_error "Please ensure program files are in the correct location"
    exit 1
fi

print_status "Program directory: $PROGRAM_DIR"

echo ""
echo "=== STEP 4: CREATE STARTUP SCRIPTS ==="
echo ""

cd "$PROGRAM_DIR"

# Create the absolute path startup script
print_status "Creating absolute path startup script..."
cat > start_spectrometer_absolute.sh << EOF
#!/bin/bash
# Gamma-ray Spectrometer startup script with absolute paths
# ASCII-only to avoid encoding issues

echo "========================================"
echo "GAMMA-RAY SPECTROMETER STARTUP"
echo "========================================"

# Absolute path to program directory
PROGRAM_DIR="$PROGRAM_DIR"
cd "\$PROGRAM_DIR" || {
    echo "ERROR: Cannot change to directory \$PROGRAM_DIR"
    exit 1
}

echo "Program directory: \$PROGRAM_DIR"

# Virtual environment path - absolute
VENV_PATH="$VENV_PATH"
if [ ! -d "\$VENV_PATH" ]; then
    echo "ERROR: Virtual environment not found at \$VENV_PATH"
    exit 1
fi

echo "Virtual environment: \$VENV_PATH"

# Activate virtual environment
if [ -z "\$VIRTUAL_ENV" ]; then
    source "\$VENV_PATH/bin/activate" || {
        echo "ERROR: Failed to activate virtual environment"
        exit 1
    }
    echo "Virtual environment activated"
else
    echo "Already in virtual environment: \$VIRTUAL_ENV"
fi

echo "Python: \$(which python3)"
echo "Python version: \$(python3 --version 2>&1)"

# Set environment variables for Qt
export PYQTGRAPH_QT_LIB=PyQt5
export QT_QPA_PLATFORM=xcb
export QT_OPENGL=software
export QT_FONT_DPI=96
export QT_AUTO_SCREEN_SCALE_FACTOR=1
export QT_SCALE_FACTOR=1.0
export QT_SCREEN_SCALE_FACTORS=1
export DISPLAY=:0
export QT_LOGGING_RULES=qt.qpa.*=false
export LOG_LEVEL=INFO
export NO_AT_BRIDGE=1
export QT_IM_MODULE=none
export GTK_IM_MODULE=none
export XMODIFIERS=@im=none
export CLUTTER_IM_MODULE=none
export ONBOARD_PRELOAD_SYMBOLS=1
export ONBOARD_DISABLE_DBUS=0
export USE_SOFTWARE_KEYBOARD=1
export ENABLE_LOGIN_KEYBOARD=1
export ALLOW_VIEWER_SETTINGS=0

# Disable GNOME OSK to avoid double keyboards when using internal keyboard
gsettings set org.gnome.desktop.a11y.applications screen-keyboard-enabled false >/dev/null 2>&1 || true

echo ""
echo "Environment variables set"
echo "========================================"

# Check Python dependencies
echo "Checking Python dependencies..."
if python3 -c "import PyQt5, pyqtgraph, serial, numpy, pandas" 2>/dev/null; then
    echo "Dependencies OK"
else
    echo "ERROR: Missing Python dependencies"
    echo "Run: pip install -r requirements.txt"
    exit 1
fi

echo ""
echo "Starting main program..."
echo "========================================"

# Run main.py with fullscreen option
exec python3 main.py --fullscreen
EOF

chmod +x start_spectrometer_absolute.sh
print_status "Created start_spectrometer_absolute.sh"

# Create a simple virtual environment wrapper
print_status "Creating virtual environment wrapper script..."
cat > start_spectrometer_simple.sh << EOF
#!/bin/bash
# Simple virtual environment wrapper startup script
# ASCII-only output to avoid encoding issues

echo "========================================"
echo "SPECTROMETER VIRTUAL ENVIRONMENT STARTUP"
echo "========================================"

# Get script directory
SCRIPT_DIR="\$(cd "\$(dirname "\${BASH_SOURCE[0]}")" && pwd)"
cd "\$SCRIPT_DIR"

echo "DIR: \$SCRIPT_DIR"

# Check virtual environment - try multiple possible locations
VENV_PATHS=(
    "\$SCRIPT_DIR/$VENV_NAME"
    "$VENV_PATH"
    "\$HOME/$VENV_NAME"
)

VENV_PATH=""
for venv_test in "\${VENV_PATHS[@]}"; do
    if [ -d "\$venv_test" ] && [ -f "\$venv_test/bin/activate" ]; then
        VENV_PATH="\$venv_test"
        echo "VENV: \$VENV_PATH"
        break
    fi
done

if [ -z "\$VENV_PATH" ]; then
    echo "ERROR: No virtual environment found"
    echo "Checked:"
    for venv_test in "\${VENV_PATHS[@]}"; do
        echo "  \$venv_test"
    done
    exit 1
fi

# Check if already in a virtual environment
if [ -n "\$VIRTUAL_ENV" ]; then
    echo "ALREADY IN VENV: \$VIRTUAL_ENV"
    if [ "\$VIRTUAL_ENV" != "\$VENV_PATH" ]; then
        echo "WARNING: Different venv (\$VIRTUAL_ENV) vs expected (\$VENV_PATH)"
    fi
else
    # Activate virtual environment
    echo "ACTIVATING: \$VENV_PATH"
    source "\$VENV_PATH/bin/activate"
    
    if [ -z "\$VIRTUAL_ENV" ]; then
        echo "ERROR: Failed to activate virtual environment"
        exit 1
    fi
    
    echo "ACTIVATED: \$VIRTUAL_ENV"
fi

echo "PYTHON: \$(which python3)"
echo "PYTHON VERSION: \$(python3 --version 2>&1)"

# Set environment variables
export PYQTGRAPH_QT_LIB=PyQt5
export QT_QPA_PLATFORM=xcb
export QT_OPENGL=software
export QT_FONT_DPI=96
export QT_AUTO_SCREEN_SCALE_FACTOR=1
export QT_SCALE_FACTOR=1.0
export QT_SCREEN_SCALE_FACTORS=1
export DISPLAY=:0
export QT_LOGGING_RULES=qt.qpa.*=false
export LOG_LEVEL=INFO
export NO_AT_BRIDGE=1
export QT_IM_MODULE=none
export GTK_IM_MODULE=none
export XMODIFIERS=@im=none
export CLUTTER_IM_MODULE=none
export ONBOARD_PRELOAD_SYMBOLS=1
export ONBOARD_DISABLE_DBUS=0
export USE_SOFTWARE_KEYBOARD=1
export ENABLE_LOGIN_KEYBOARD=1
export ALLOW_VIEWER_SETTINGS=0

# Disable GNOME OSK to avoid double keyboards when using internal keyboard
gsettings set org.gnome.desktop.a11y.applications screen-keyboard-enabled false >/dev/null 2>&1 || true

echo ""
echo "ENV VARS SET"
echo "========================================"

# Check Python dependencies
echo "CHECKING DEPS..."
if python3 -c "import PyQt5, pyqtgraph, serial, numpy, pandas" 2>/dev/null; then
    echo "DEPS OK"
else
    echo "ERROR: Missing Python dependencies"
    echo "Run: pip install -r requirements.txt"
    exit 1
fi

echo ""
echo "STARTING MAIN PROGRAM..."
echo "========================================"

# Run main program
exec python3 main.py --fullscreen
EOF

chmod +x start_spectrometer_simple.sh
print_status "Created start_spectrometer_simple.sh"

echo ""
echo "=== STEP 5: CREATE DESKTOP SHORTCUT ==="
echo ""

DESKTOP_FILE="$HOME/Desktop/spectrometer.desktop"
print_status "Creating desktop shortcut: $DESKTOP_FILE"

cat > "$DESKTOP_FILE" << EOF
[Desktop Entry]
Name=Gamma-ray Spectrometer
Comment=Radiation Spectrometer Data Acquisition Software
Exec=/bin/bash -c "cd '$PROGRAM_DIR' && ./start_spectrometer_absolute.sh > /home/$CURRENT_USER/spectrometer.log 2>&1"
Icon=$PROGRAM_DIR/core/icons/icon.png
Terminal=false
Type=Application
Categories=Science;Education;Utility;
Keywords=spectrometer;radiation;gamma;data acquisition;
StartupNotify=true
EOF

chmod +x "$DESKTOP_FILE"
print_status "Desktop shortcut created"

echo ""
echo "=== STEP 6: SETUP AUTOSTART (Optional) ==="
echo ""

read -p "Do you want to set up automatic startup on login? (y/N): " setup_autostart

if [[ "$setup_autostart" == "y" || "$setup_autostart" == "Y" ]]; then
    print_status "Setting up autostart..."
    
    AUTOSTART_DIR="$HOME/.config/autostart"
    mkdir -p "$AUTOSTART_DIR"
    
    AUTOSTART_FILE="$AUTOSTART_DIR/spectrometer.desktop"
    
    cat > "$AUTOSTART_FILE" << EOF
[Desktop Entry]
Name=Gamma-ray Spectrometer
Comment=Radiation Spectrometer Data Acquisition
Exec=/bin/bash -c "cd '$PROGRAM_DIR' && ./start_spectrometer_absolute.sh > /home/$CURRENT_USER/spectrometer.log 2>&1"
Icon=$PROGRAM_DIR/core/icons/icon.png
Terminal=false
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
EOF
    
    print_status "Autostart configured at $AUTOSTART_FILE"
    
    # Important warning about autologin
    echo ""
    print_warning "IMPORTANT: For autostart to work, you need to:"
    print_warning "1. Enable automatic login in System Settings ¡ú Users"
    print_warning "2. OR manually edit /etc/lightdm/lightdm.conf"
    print_warning "   Add: autologin-user=$CURRENT_USER"
    print_warning "        autologin-user-timeout=0"
else
    print_status "Skipping autostart setup"
fi

echo ""
echo "=== STEP 6B: SETUP USB AUTO EXPORT (Optional) ==="
echo ""

read -p "Do you want to enable USB auto-export? (y/N): " setup_usb

if [[ "$setup_usb" == "y" || "$setup_usb" == "Y" ]]; then
    print_status "Setting up USB auto-export..."

    # Ensure scripts exist
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

    # Install scripts
    sudo cp "$PROGRAM_DIR/export_to_usb.sh" /usr/local/bin/export_to_usb.sh
    sudo cp "$PROGRAM_DIR/spectrometer-usb-export-wrapper.sh" /usr/local/bin/spectrometer-usb-export-wrapper.sh
    sudo chmod +x /usr/local/bin/export_to_usb.sh /usr/local/bin/spectrometer-usb-export-wrapper.sh

    # Install udev rule
    sudo cp "$PROGRAM_DIR/99-usb-export.rules" /etc/udev/rules.d/99-usb-export.rules

    # Install systemd unit
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

    sudo systemctl daemon-reload
    sudo udevadm control --reload-rules
    sudo udevadm trigger --action=add --subsystem-match=block

    print_status "USB auto-export enabled"

    # Auto-detect USB partition (first removable partition)
    detect_usb_partition() {
        lsblk -nrpo NAME,TYPE,RM | awk '$2=="part" && $3=="1" {print $1; exit}'
    }

    # Optional test
    echo ""
    read -p "Do you want to run a USB export test now? (y/N): " run_usb_test
    if [[ "$run_usb_test" == "y" || "$run_usb_test" == "Y" ]]; then
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
else
    print_status "Skipping USB auto-export setup"
fi

echo ""
echo "=== STEP 7: SETUP SERIAL PORT PERMISSIONS ==="
echo ""

print_status "Setting up serial port permissions..."
if ! groups $CURRENT_USER | grep -q "dialout"; then
    sudo usermod -a -G dialout $CURRENT_USER
    print_status "Added user $CURRENT_USER to dialout group"
    print_warning "You may need to log out and log back in for changes to take effect"
else
    print_status "User already in dialout group"
fi

echo ""
echo "=== STEP 8: CREATE DIAGNOSTIC TOOLS ==="
echo ""

# Create diagnostic script
print_status "Creating diagnostic script..."
cat > diagnose_spectrometer.sh << EOF
#!/bin/bash
# Diagnostic script for Gamma-ray Spectrometer

echo "========================================"
echo "SPECTROMETER DIAGNOSTICS"
echo "========================================"
echo "Current user: \$(whoami)"
echo "Date: \$(date)"
echo ""

echo "1. Checking virtual environment..."
if [ -d "$VENV_PATH" ]; then
    echo "   ? Virtual environment found: $VENV_PATH"
    source "$VENV_PATH/bin/activate"
    echo "   Python: \$(which python3)"
    echo "   Python version: \$(python3 --version 2>&1)"
    
    echo "   Checking packages..."
    python3 -c "import PyQt5; print('    ? PyQt5')" 2>/dev/null || echo "    ? PyQt5"
    python3 -c "import pyqtgraph; print('    ? pyqtgraph')" 2>/dev/null || echo "    ? pyqtgraph"
    python3 -c "import serial; print('    ? pyserial')" 2>/dev/null || echo "    ? pyserial"
    python3 -c "import numpy; print('    ? numpy')" 2>/dev/null || echo "    ? numpy"
    python3 -c "import pandas; print('    ? pandas')" 2>/dev/null || echo "    ? pandas"
    
    deactivate
else
    echo "   ? Virtual environment not found at $VENV_PATH"
fi

echo ""
echo "2. Checking program directory..."
if [ -d "$PROGRAM_DIR" ]; then
    echo "   ? Program directory exists"
    if [ -f "$PROGRAM_DIR/main.py" ]; then
        echo "   ? main.py found"
    else
        echo "   ? main.py not found"
    fi
else
    echo "   ? Program directory not found"
fi

echo ""
echo "3. Checking startup scripts..."
if [ -f "$PROGRAM_DIR/start_spectrometer_absolute.sh" ]; then
    echo "   ? start_spectrometer_absolute.sh found"
    if [ -x "$PROGRAM_DIR/start_spectrometer_absolute.sh" ]; then
        echo "   ? Script is executable"
    else
        echo "   ? Script is not executable"
    fi
else
    echo "   ? start_spectrometer_absolute.sh not found"
fi

echo ""
echo "4. Checking desktop shortcut..."
if [ -f "\$HOME/Desktop/spectrometer.desktop" ]; then
    echo "   ? Desktop shortcut exists"
else
    echo "   ? Desktop shortcut not found"
fi

echo ""
echo "5. Checking autostart configuration..."
if [ -f "\$HOME/.config/autostart/spectrometer.desktop" ]; then
    echo "   ? Autostart configuration exists"
else
    echo "   ? No autostart configuration"
fi

echo ""
echo "6. Checking serial port permissions..."
if groups \$(whoami) | grep -q "dialout"; then
    echo "   ? User has serial port access"
else
    echo "   ? User not in dialout group"
fi

echo ""
echo "7. Testing program startup (5 seconds)..."
cd "$PROGRAM_DIR" 2>/dev/null
if [ \$? -eq 0 ]; then
    timeout 5 ./start_spectrometer_absolute.sh 2>&1 | tail -5
    echo "   Test completed"
else
    echo "   ? Cannot access program directory"
fi

echo ""
echo "========================================"
echo "DIAGNOSTICS COMPLETE"
echo "========================================"
EOF

chmod +x diagnose_spectrometer.sh
print_status "Created diagnose_spectrometer.sh"

echo ""
echo "=== STEP 9: FINAL TEST ==="
echo ""

print_status "Testing program startup (10-second test)..."
cd "$PROGRAM_DIR"
timeout 10 ./start_spectrometer_absolute.sh 2>&1 | tail -10

if [ $? -eq 124 ]; then
    print_status "Program started successfully (stopped after 10 seconds)"
else
    print_warning "Program may have exited early - check above output"
fi

echo ""
echo "========================================"
echo "INSTALLATION COMPLETE"
echo "========================================"
echo ""
print_status "Summary of installation:"
echo "  - Virtual environment: $VENV_PATH"
echo "  - Program directory: $PROGRAM_DIR"
echo "  - Desktop shortcut: $HOME/Desktop/spectrometer.desktop"
echo "  - Startup script: $PROGRAM_DIR/start_spectrometer_absolute.sh"
echo "  - Diagnostic tool: $PROGRAM_DIR/diagnose_spectrometer.sh"
echo ""
print_status "Next steps:"
echo "  1. Double-click the 'Gamma-ray Spectrometer' icon on your desktop"
echo "  2. If you set up autostart, enable automatic login in system settings"
echo "  3. For troubleshooting, run: ./diagnose_spectrometer.sh"
echo ""
print_status "Installation complete! The spectrometer software is ready to use."
echo "========================================"
