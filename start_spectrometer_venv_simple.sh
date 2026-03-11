#!/bin/bash
# Simple virtual environment wrapper startup script
# ASCII-only output to avoid encoding issues

echo "========================================"
echo "SPECTROMETER VIRTUAL ENVIRONMENT STARTUP"
echo "========================================"

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "DIR: $SCRIPT_DIR"

# Check virtual environment - try multiple possible locations
VENV_PATHS=(
    "$SCRIPT_DIR/myenv"
    "/home/raysen/myenv"
    "$HOME/myenv"
)

VENV_PATH=""
for venv_test in "${VENV_PATHS[@]}"; do
    if [ -d "$venv_test" ] && [ -f "$venv_test/bin/activate" ]; then
        VENV_PATH="$venv_test"
        echo "VENV: $VENV_PATH"
        break
    fi
done

if [ -z "$VENV_PATH" ]; then
    echo "ERROR: No virtual environment found"
    echo "Checked:"
    for venv_test in "${VENV_PATHS[@]}"; do
        echo "  $venv_test"
    done
    exit 1
fi

# Check if already in a virtual environment
if [ -n "$VIRTUAL_ENV" ]; then
    echo "ALREADY IN VENV: $VIRTUAL_ENV"
    if [ "$VIRTUAL_ENV" != "$VENV_PATH" ]; then
        echo "WARNING: Different venv ($VIRTUAL_ENV) vs expected ($VENV_PATH)"
    fi
else
    # Activate virtual environment
    echo "ACTIVATING: $VENV_PATH"
    source "$VENV_PATH/bin/activate"
    
    if [ -z "$VIRTUAL_ENV" ]; then
        echo "ERROR: Failed to activate virtual environment"
        exit 1
    fi
    
    echo "ACTIVATED: $VIRTUAL_ENV"
fi

echo "PYTHON: $(which python3)"
echo "PYTHON VERSION: $(python3 --version 2>&1)"

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

# Check and prepare startup script
if [ ! -f "start_spectrometer_rpi.sh" ]; then
    echo "ERROR: start_spectrometer_rpi.sh not found"
    exit 1
fi

chmod +x start_spectrometer_rpi.sh 2>/dev/null

echo ""
echo "STARTING MAIN PROGRAM..."
echo "========================================"

# Run main program
exec ./start_spectrometer_rpi.sh "$@"
