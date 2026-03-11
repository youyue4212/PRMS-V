#!/bin/bash
# Gamma-ray Spectrometer startup script with absolute paths
# ASCII-only to avoid encoding issues

echo "========================================"
echo "GAMMA-RAY SPECTROMETER STARTUP"
echo "========================================"

# Absolute path to program directory
PROGRAM_DIR="/home/raysen/user/daq_tablet"
cd "$PROGRAM_DIR" || {
    echo "ERROR: Cannot change to directory $PROGRAM_DIR"
    exit 1
}

echo "Program directory: $PROGRAM_DIR"

# Virtual environment path - absolute
VENV_PATH="/home/raysen/myenv"
if [ ! -d "$VENV_PATH" ]; then
    echo "ERROR: Virtual environment not found at $VENV_PATH"
    exit 1
fi

echo "Virtual environment: $VENV_PATH"

# Activate virtual environment
if [ -z "$VIRTUAL_ENV" ]; then
    source "$VENV_PATH/bin/activate" || {
        echo "ERROR: Failed to activate virtual environment"
        exit 1
    }
    echo "Virtual environment activated"
else
    echo "Already in virtual environment: $VIRTUAL_ENV"
fi

echo "Python: $(which python3)"
echo "Python version: $(python3 --version 2>&1)"

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
