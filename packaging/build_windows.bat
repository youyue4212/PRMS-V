@echo off
REM 在 Windows 开发机上打包（生成的 exe 只能给 Windows 用，不能给 Linux 单板机用）
REM 产物是目录模式：必须整夹拷贝 daq_tablet\（含 _internal），不能只拷 exe。
setlocal EnableDelayedExpansion
cd /d "%~dp0\.."

echo ========================================
echo  daq_tablet Windows 打包
echo ========================================

python -c "import sys; print('Python', sys.version); print('Prefix', sys.base_prefix); v=sys.version_info; raise SystemExit(0 if (v.major, v.minor) >= (3, 10) else 1)"
if errorlevel 1 (
    echo [错误] 需要 Python 3.10 及以上。
    pause
    exit /b 1
)

python -c "import sys; v=sys.version_info; print('[提示] 当前是 Python %d.%d。PyQt5 在 3.12/3.13 上更稳；3.14 可用但目标机需较新的 VC 运行库。' % (v.major, v.minor))"

if not exist .venv_pack (
    python -m venv .venv_pack
)
call .venv_pack\Scripts\activate.bat

python -m pip install -U pip wheel
REM PyInstaller 6.15 起才支持 Python 3.14
pip install "pyinstaller>=6.16" PyQt5 PyQtWebEngine pyqtgraph numpy pandas pyserial openpyxl psutil scipy

cd packaging
if exist dist rmdir /s /q dist
if exist build rmdir /s /q build

pyinstaller --noconfirm --clean daq_tablet.spec
if errorlevel 1 (
    echo [错误] PyInstaller 打包失败。
    pause
    exit /b 1
)

set "DIST_DIR=%cd%\dist\daq_tablet"
set "INTERNAL=%DIST_DIR%\_internal"
if not exist "%DIST_DIR%\daq_tablet.exe" (
    echo [错误] 未生成 dist\daq_tablet\daq_tablet.exe
    pause
    exit /b 1
)

REM 用未压缩的官方 DLL 覆盖，避免 UPX / 收集遗漏导致 LoadLibrary 失败
for /f "delims=" %%I in ('python -c "import sys; print(sys.base_prefix)"') do set "PYDIR=%%I"
for %%D in (python3.dll python314.dll python313.dll python312.dll VCRUNTIME140.dll VCRUNTIME140_1.dll vcruntime140.dll vcruntime140_1.dll) do (
    if exist "%PYDIR%\%%D" (
        copy /y "%PYDIR%\%%D" "%INTERNAL%\%%D" >nul
    )
)

copy /y "%~dp0使用说明.txt" "%DIST_DIR%\使用说明.txt" >nul

set "PYDLL="
for %%D in (python314.dll python313.dll python312.dll python311.dll python310.dll) do (
    if exist "%INTERNAL%\%%D" set "PYDLL=%%D"
)
if not defined PYDLL (
    echo [错误] _internal 里没有 python3xx.dll，这个包无法在其它电脑运行。
    pause
    exit /b 1
)

echo.
echo ========================================
echo  完成。产物：packaging\dist\daq_tablet\
echo ========================================
echo  必须把整个 daq_tablet 文件夹一起拷走，结构如下：
echo    daq_tablet\
echo      daq_tablet.exe
echo      _internal\          ^(已包含 %PYDLL%^)
echo      使用说明.txt
echo.
echo  不要只把 exe 拷到桌面，否则会报：
echo    Failed to load Python DLL ...\_internal\python3xx.dll
echo ========================================
pause
