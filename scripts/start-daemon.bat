@echo off
chcp 936 >nul 2>&1
rem ============================================================================
rem  boardwise daemon 启动器
rem  这个窗口就是 daemon 窗口：保持开着；关掉窗口或按 Ctrl-C 就是停止 daemon。
rem  停止还可以用 scripts\stop-daemon.bat，或者在另一个窗口跑 bridge status 看状态。
rem  本文件是 ANSI/GBK 编码，第 2 行切到 936；两行都要留着，否则中文会乱。
rem ============================================================================
setlocal EnableExtensions
title boardwise daemon

set "ROOT=%~dp0.."
pushd "%ROOT%" >nul 2>&1
if errorlevel 1 (
  echo [错误] 进不去仓库目录：%ROOT%
  pause
  exit /b 1
)
set "ROOT=%CD%"

if not exist "pyproject.toml" (
  echo [错误] 这里不是 boardwise 仓库根目录：找不到 pyproject.toml
  echo         本脚本要放在仓库的 scripts 文件夹里运行。
  popd
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  echo [错误] 找不到 .venv：boardwise 还没装。
  echo         请先双击 scripts\install.bat 安装，再回来双击本脚本。
  popd
  pause
  exit /b 1
)

set "PORT=61190"
if defined BOARDWISE_PORT set "PORT=%BOARDWISE_PORT%"

echo ============================================================================
echo  boardwise daemon
echo  监听端口：%PORT%   要换端口就先设环境变量 BOARDWISE_PORT
echo  这个窗口要保持开着：关掉它或者按 Ctrl-C，就等于把桥拆了。
echo ============================================================================
echo.

rem 端口已经被占用，说明多半有 daemon 在跑：只报状态，不再起第二个
set "LISTENER="
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /c:":%PORT%" ^| findstr /c:"LISTENING"') do set "LISTENER=%%P"
if defined LISTENER (
  echo [提示] 端口 %PORT% 上已经有进程在监听，PID %LISTENER%：daemon 多半已经在跑了。
  echo         下面是当前的连接状态。想重启，先双击 scripts\stop-daemon.bat。
  echo.
  ".venv\Scripts\python.exe" -m boardwise.cli bridge status
  echo.
  popd
  pause
  exit /b 0
)

echo 下面每 60 秒打印一次连接状态，只打印含 connector: 的那两行：
echo.
start "" /b cmd /c "for /l %%i in (1,1,2880) do @(.venv\Scripts\python.exe -m boardwise.cli bridge status 2>nul | findstr connector: & ping -n 61 127.0.0.1 >nul)"
echo 正在启动 daemon ...（编辑器里的扩展连上来时会自动配对，本窗口会打印一条带指纹的公告）
echo ----------------------------------------------------------------------------
echo.

".venv\Scripts\python.exe" -m boardwise.cli bridge start
set "RC=%ERRORLEVEL%"

echo.
echo ----------------------------------------------------------------------------
echo daemon 已经退出，退出码 %RC%
echo.
".venv\Scripts\python.exe" -m boardwise.cli bridge status
echo.
echo 想再起一次就重新双击本脚本；要停 daemon 用 scripts\stop-daemon.bat。
popd
pause
exit /b 0
