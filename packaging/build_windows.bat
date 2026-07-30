@echo off
REM 在 Windows 开发机上打包（生成的 exe 只能给 Windows 用，不能给 Linux 单板机用）
setlocal
cd /d "%~dp0\.."

if not exist .venv_pack (
    python -m venv .venv_pack
)
call .venv_pack\Scripts\activate.bat

python -m pip install -U pip wheel
pip install pyinstaller PyQt5 pyqtgraph numpy pandas pyserial openpyxl psutil scipy

cd packaging
if exist dist rmdir /s /q dist
if exist build rmdir /s /q build

pyinstaller --noconfirm --clean daq_tablet.spec

echo.
echo 完成。产物在 packaging\dist\daq_tablet\
echo 把整个 daq_tablet 文件夹拷到 Windows 电脑即可双击 daq_tablet.exe
pause
