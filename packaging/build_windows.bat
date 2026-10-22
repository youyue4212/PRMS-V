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

echo.
echo [1/4] 结束可能占用 dist 的进程 ...
taskkill /F /IM daq_tablet.exe >nul 2>&1
powershell -NoProfile -Command ^
  "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -match 'daq_tablet' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1
timeout /t 2 /nobreak >nul

cd packaging
if not exist dist mkdir dist

REM 写到新目录，避免 PyInstaller COLLECT 强删被锁定的 dist\daq_tablet
set "PI_STAGE=dist\stage_%RANDOM%_%RANDOM%"
echo [2/4] PyInstaller 输出到 %PI_STAGE% （不覆盖旧 dist\daq_tablet）...
if exist build rmdir /s /q build 2>nul

pyinstaller --noconfirm --clean --distpath "%PI_STAGE%" daq_tablet.spec
if errorlevel 1 (
    echo [错误] PyInstaller 打包失败。
    if exist "%PI_STAGE%" rmdir /s /q "%PI_STAGE%" 2>nul
    pause
    exit /b 1
)

set "STAGE_APP=%CD%\%PI_STAGE%\daq_tablet"
set "DIST_DIR=%CD%\dist\daq_tablet"
if not exist "%STAGE_APP%\daq_tablet.exe" (
    echo [错误] 未生成 %PI_STAGE%\daq_tablet\daq_tablet.exe
    pause
    exit /b 1
)

set "INTERNAL=%STAGE_APP%\_internal"
for /f "delims=" %%I in ('python -c "import sys; print(sys.base_prefix)"') do set "PYDIR=%%I"
for %%D in (python3.dll python314.dll python313.dll python312.dll VCRUNTIME140.dll VCRUNTIME140_1.dll vcruntime140.dll vcruntime140_1.dll) do (
    if exist "%PYDIR%\%%D" (
        copy /y "%PYDIR%\%%D" "%INTERNAL%\%%D" >nul
    )
)
REM python314.dll 还依赖 python3.dll；二者必须同在 _internal
if exist "%PYDIR%\python3.dll" if not exist "%INTERNAL%\python3.dll" (
    copy /y "%PYDIR%\python3.dll" "%INTERNAL%\python3.dll" >nul
)
if exist build\daq_tablet (
    echo 本目录 exe 不能单独运行，请用 packaging\dist\daq_tablet\daq_tablet.exe> build\daq_tablet\勿在此运行.txt
)
copy /y "%~dp0使用说明.txt" "%STAGE_APP%\使用说明.txt" >nul

REM 发布失败时仍用 stage 目录校验与提示，避免误报「没有 python3xx.dll」
set "RELEASE_DIR=%STAGE_APP%"
set "INTERNAL=%STAGE_APP%\_internal"

echo [3/4] 发布到 packaging\dist\daq_tablet ...
taskkill /F /IM daq_tablet.exe >nul 2>&1
timeout /t 1 /nobreak >nul

set "PUBLISH_OK=0"
if exist "%DIST_DIR%" (
    set "OLD=dist\daq_tablet_old_%RANDOM%"
    move /Y "%DIST_DIR%" "!OLD!" >nul 2>&1
    if exist "%DIST_DIR%" (
        echo [警告] 旧 dist\daq_tablet 被占用，跳过覆盖；请直接使用本次 stage 目录：
        echo   %STAGE_APP%
        goto :done_stage
    )
    if exist "!OLD!" rmdir /s /q "!OLD!" 2>nul
)

move /Y "%STAGE_APP%" "%DIST_DIR%" >nul 2>&1
if not errorlevel 1 if exist "%DIST_DIR%\daq_tablet.exe" (
    set "PUBLISH_OK=1"
    set "RELEASE_DIR=%DIST_DIR%"
    set "INTERNAL=%DIST_DIR%\_internal"
    if exist "%PI_STAGE%" rmdir /s /q "%PI_STAGE%" 2>nul
) else (
    echo [警告] 无法 move 到 dist\daq_tablet（拒绝访问/被占用），改用 robocopy ...
    if not exist "%DIST_DIR%" mkdir "%DIST_DIR%" 2>nul
    robocopy "%STAGE_APP%" "%DIST_DIR%" /E /NFL /NDL /NJH /NJS /NC /NS /R:2 /W:2 >nul
    if exist "%DIST_DIR%\daq_tablet.exe" (
        set "PUBLISH_OK=1"
        set "RELEASE_DIR=%DIST_DIR%"
        set "INTERNAL=%DIST_DIR%\_internal"
        echo [提示] 已复制到 dist\daq_tablet；可手动删除 stage：%PI_STAGE%
    ) else (
        echo [警告] robocopy 也未完成；请关闭占用程序后，直接整夹拷贝：
        echo   %STAGE_APP%
    )
)

:done_stage
set "PYDLL="
for %%D in (python314.dll python313.dll python312.dll python311.dll python310.dll) do (
    if exist "%INTERNAL%\%%D" set "PYDLL=%%D"
)
if not defined PYDLL (
    echo [错误] 在下列目录的 _internal 中未找到 python3xx.dll：
    echo   %INTERNAL%
    echo 若 PyInstaller 已成功，请检查 stage 是否被误删；可重新运行 build_windows.bat。
    pause
    exit /b 1
)

echo.
echo ========================================
if "!PUBLISH_OK!"=="1" (
    echo  完成。产物：packaging\dist\daq_tablet\
) else (
    echo  完成（请整夹拷贝，路径如下）：
    echo  !RELEASE_DIR!
)
echo  可执行文件：!RELEASE_DIR!\daq_tablet.exe
echo ========================================
echo  必须把整个 daq_tablet 文件夹一起拷走，结构如下：
echo    daq_tablet\
echo      daq_tablet.exe
echo      _internal\          ^(已包含 %PYDLL%^)
echo      使用说明.txt
echo.
echo  不要只把 exe 拷到桌面，否则会报：
echo    Failed to load Python DLL ...\_internal\python3xx.dll
echo.
echo  不要运行 packaging\build\daq_tablet\daq_tablet.exe （中间产物，必失败）
echo  目标机仍失败时：安装 VC++ 2015-2022 x64
echo    https://aka.ms/vs/17/release/vc_redist.x64.exe
echo ========================================
pause
