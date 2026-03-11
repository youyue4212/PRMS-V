#!/bin/bash
# Gamma-ray Spectrometer startup script for Raspberry Pi
# Compatible with all Raspberry Pi versions

echo "========================================"
echo "Gamma-ray Spectrometer Raspberry Pi Edition Starting..."
echo "========================================"

# Set environment variables - fix Qt issues on Raspberry Pi
export PYQTGRAPH_QT_LIB=PyQt5

# Virtual keyboard compatibility configuration
# Option 1: Use X11 display server (better virtual keyboard compatibility)
if [ -n "$WAYLAND_DISPLAY" ]; then
    echo "Wayland display server detected, switching to X11 for better virtual keyboard compatibility"
    export QT_QPA_PLATFORM=xcb
else
    # If Wayland not detected, use default platform
    export QT_QPA_PLATFORM=xcb
fi

export QT_OPENGL=software
export QT_FONT_DPI=96
export QT_AUTO_SCREEN_SCALE_FACTOR=1
export QT_SCALE_FACTOR=1.0
export QT_SCREEN_SCALE_FACTORS=1
export DISPLAY=:0
export QT_LOGGING_RULES=qt.qpa.*=false
export LOG_LEVEL=INFO

# Disable AT-SPI bridge to prevent segmentation faults and warnings
export NO_AT_BRIDGE=1

# Virtual keyboard input fix - disable input method modules
export QT_IM_MODULE=none
export GTK_IM_MODULE=none
export XMODIFIERS=@im=none
export CLUTTER_IM_MODULE=none

# Add virtual keyboard support environment variables
export ONBOARD_PRELOAD_SYMBOLS=1
export ONBOARD_DISABLE_DBUS=0
export USE_SOFTWARE_KEYBOARD=1
export ENABLE_LOGIN_KEYBOARD=1
export ALLOW_VIEWER_SETTINGS=0

# Disable GNOME OSK to avoid double keyboards when using internal keyboard
gsettings set org.gnome.desktop.a11y.applications screen-keyboard-enabled false >/dev/null 2>&1 || true

# Set Python path
export PYTHONPATH="$(dirname "$(realpath "$0")"):$PYTHONPATH"

# Get script directory
SCRIPT_DIR="$(dirname "$(realpath "$0")")"
cd "$SCRIPT_DIR"

echo "Current directory: $SCRIPT_DIR"
echo "Environment variables set:"
echo "  PYQTGRAPH_QT_LIB=$PYQTGRAPH_QT_LIB"
echo "  QT_QPA_PLATFORM=$QT_QPA_PLATFORM"
echo "  QT_OPENGL=$QT_OPENGL"
echo "  QT_FONT_DPI=$QT_FONT_DPI"
echo "  QT_IM_MODULE=$QT_IM_MODULE"
echo "========================================"

# Check if Python3 is available
if ! command -v python3 &> /dev/null; then
    echo "ERROR: python3 not found, please install Python3"
    echo "Run: sudo apt-get install python3"
    exit 1
fi

# Check dependencies
echo "Checking Python dependencies..."
python3 -c "import PyQt5, pyqtgraph, serial, numpy, pandas" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "WARNING: Some Python dependencies missing, attempting to install..."
    if [ -f "requirements.txt" ]; then
        pip3 install -r requirements.txt
    else
        echo "ERROR: requirements.txt file not found"
        echo "Please install dependencies manually:"
        echo "sudo apt-get install python3-pyqt5 python3-pyqt5.qtwebkit"
        echo "pip3 install pyqtgraph pyserial numpy pandas"
        exit 1
    fi
fi

# Check serial port permissions
echo "Checking serial port permissions..."
if ! groups $USER | grep -q "dialout"; then
    echo "WARNING: User not in dialout group, serial port access may be restricted"
    echo "Run: sudo usermod -a -G dialout $USER"
    echo "Then log out and log back in"
fi

# Check log directory
if [ ! -d "core/logs" ]; then
    mkdir -p core/logs
    echo "Created log directory: core/logs"
fi

# Start the program
echo "Starting main program..."
echo "========================================"

echo "Virtual keyboard compatibility configuration:"
echo "  QT_QPA_PLATFORM=$QT_QPA_PLATFORM"
echo "  QT_IM_MODULE=$QT_IM_MODULE"
echo "  GTK_IM_MODULE=$GTK_IM_MODULE"
echo "  NO_AT_BRIDGE=$NO_AT_BRIDGE"

# Check and install virtual keyboard support
echo "Checking virtual keyboard support..."
if command -v onboard &> /dev/null; then
    echo "? onboard virtual keyboard installed"
else
    echo "? onboard not installed, recommended for best virtual keyboard experience"
    echo "  Run: sudo apt install onboard"
fi

# Run main program - with virtual keyboard debugging options
echo "Starting main program (with virtual keyboard debugging)..."
echo "========================================"

# Run main program - use fullscreen mode
#python3 main.py --resizable --keyboard-debug
python3 main.py --fullscreen --keyboard-debug

# Handle program exit
EXIT_CODE=$?
echo "========================================"
echo "Program exited with code: $EXIT_CODE"
echo "========================================"

if [ $EXIT_CODE -eq 0 ]; then
    echo "Program exited normally"
elif [ $EXIT_CODE -eq 134 ]; then
    echo "Program exited abnormally (SIGABRT), possibly Qt issue"
    echo "Check environment variable settings"
else
    echo "Program exit code: $EXIT_CODE"
fi

# Wait for user input to see error messages (only in non-interactive terminals)
if [ ! -t 0 ] && [ $EXIT_CODE -ne 0 ]; then
    echo "Program exited abnormally, waiting 10 seconds before closing..."
    sleep 10
elif [ $EXIT_CODE -ne 0 ]; then
    read -p "Press Enter to close terminal..."
fi

exit $EXIT_CODE
