#!/bin/bash
# Virtual environment wrapper startup script
# For solving desktop launcher issues in virtual environments

echo "========================================"
echo "Spectrometer Virtual Environment Startup"
echo "========================================"

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "Current directory: $SCRIPT_DIR"

# Check virtual environment - try multiple possible locations
VENV_PATHS=(
    "$SCRIPT_DIR/myenv"           # In program directory
    "/home/raysen/myenv"          # User home directory (from user feedback)
    "$HOME/myenv"                 # Generic home directory
)

VENV_PATH=""
for venv_test in "${VENV_PATHS[@]}"; do
    if [ -d "$venv_test" ] && [ -f "$venv_test/bin/activate" ]; then
        VENV_PATH="$venv_test"
        echo "Found virtual environment: $VENV_PATH"
        break
    fi
done

if [ -z "$VENV_PATH" ]; then
    echo "ERROR: Virtual environment not found in any expected location"
    echo "Expected locations:"
    for venv_test in "${VENV_PATHS[@]}"; do
        echo "  - $venv_test"
    done
    exit 1
fi

# Check if already in a virtual environment
if [ -n "$VIRTUAL_ENV" ]; then
    echo "Already in virtual environment: $VIRTUAL_ENV"
    
    # Check if we're in the correct virtual environment
    if [ "$VIRTUAL_ENV" != "$VENV_PATH" ]; then
        echo "WARNING: Current virtual environment ($VIRTUAL_ENV) does not match expected ($VENV_PATH)"
        echo "This may cause dependency issues. Consider deactivating and letting the script activate the correct one."
    fi
else
    # Activate virtual environment
    echo "Activating virtual environment: $VENV_PATH"
    source "$VENV_PATH/bin/activate"
    
    # Check if virtual environment activation was successful
    if [ -z "$VIRTUAL_ENV" ]; then
        echo "ERROR: Virtual environment activation failed"
        exit 1
    fi
    
    echo "Virtual environment activated: $VIRTUAL_ENV"
fi

echo "Python path: $(which python3)"
echo "Python version: $(python3 --version)"

# Set environment variables - fix Raspberry Pi Qt issues
export PYQTGRAPH_QT_LIB=PyQt5

# Virtual keyboard compatibility configuration
if [ -n "$WAYLAND_DISPLAY" ]; then
    echo "Detected Wayland display server, switching to X11 for better virtual keyboard compatibility"
    export QT_QPA_PLATFORM=xcb
else
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

# Disable AT-SPI bridge to prevent segmentation faults
export NO_AT_BRIDGE=1

# Virtual keyboard input fix - disable input method module, use direct input
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

echo ""
echo "Environment variables set:"
echo "  PYQTGRAPH_QT_LIB=$PYQTGRAPH_QT_LIB"
echo "  QT_QPA_PLATFORM=$QT_QPA_PLATFORM"
echo "  QT_OPENGL=$QT_OPENGL"
echo "  QT_FONT_DPI=$QT_FONT_DPI"
echo "  QT_IM_MODULE=$QT_IM_MODULE"
echo "  USE_SOFTWARE_KEYBOARD=$USE_SOFTWARE_KEYBOARD"
echo "========================================"

# Check Python dependencies
echo "Checking Python dependencies..."
python3 -c "import PyQt5, pyqtgraph, serial, numpy, pandas" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "ERROR: Some Python dependencies are missing"
    echo "Please ensure all dependencies are installed in the virtual environment:"
    echo "  pip install -r requirements.txt"
    exit 1
fi

echo "All Python dependencies check passed"

# Check startup script
if [ ! -f "start_spectrometer_rpi.sh" ]; then
    echo "ERROR: Startup script not found: start_spectrometer_rpi.sh"
    exit 1
fi

# Give execute permission to startup script (if needed)
chmod +x start_spectrometer_rpi.sh

echo ""
echo "Starting main program..."
echo "========================================"

# Run main program
exec ./start_spectrometer_rpi.sh "$@"
