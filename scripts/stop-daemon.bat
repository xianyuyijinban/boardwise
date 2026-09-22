@echo off
chcp 936 >nul 2>&1
rem ============================================================================
rem  boardwise daemon 停止器
rem  找到监听端口的那一个进程并结束它：那就是 daemon，它不写工程文件，杀掉是安全的。
rem  端口默认 61190，和 start-daemon.bat 一样认环境变量 BOARDWISE_PORT。
rem  本文件是 ANSI/GBK 编码，第 2 行切到 936；两行都要留着，否则中文会乱。
rem ============================================================================
setlocal EnableExtensions
title boardwise 停止 daemon

set "PORT=61190"
if defined BOARDWISE_PORT set "PORT=%BOARDWISE_PORT%"

echo ============================================================================
echo  停止 boardwise daemon
echo  端口：%PORT%
echo ============================================================================
echo.

set "FOUND="
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /c:":%PORT%" ^| findstr /c:"LISTENING"') do (
  set "FOUND=1"
  echo 结束监听 %PORT% 的进程：PID %%P
  tasklist /FI "PID eq %%P" /FO TABLE
  taskkill /PID %%P /F
  if errorlevel 1 echo    [错误] 结束失败：可能需要用管理员身份运行本脚本。
)
if not defined FOUND (
  echo [提示] 端口 %PORT% 上没有在监听的进程：daemon 多半已经停了。
  echo         如果编辑器里的扩展还显示 connected，那是旧连接，重开编辑器即可。
  echo.
  pause
  exit /b 0
)
echo.
echo daemon 已经停止。daemon 那个窗口如果还开着，可以直接关掉它。
echo.
pause
exit /b 0
