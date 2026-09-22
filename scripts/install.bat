@echo off
chcp 936 >nul 2>&1
rem ============================================================================
rem  boardwise 一键安装（Windows）
rem  动作：检查 Python 3.10+ - 建 .venv - 装 boardwise - 问一句开发依赖 - 跑 doctor
rem  只动本仓库目录，不碰你的工程文件，也不改系统 PATH。
rem  可以随便重跑：已经存在的 .venv 会被复用。
rem  本文件是 ANSI/GBK 编码，第 2 行切到 936；两行都要留着，否则中文会乱。
rem ============================================================================
setlocal EnableExtensions
title boardwise 安装

set "ROOT=%~dp0.."
pushd "%ROOT%" >nul 2>&1
if errorlevel 1 (
  echo [错误] 进不去仓库目录：%ROOT%
  echo         请把 scripts 文件夹留在仓库里再运行，不要单独复制出来。
  pause
  exit /b 1
)
set "ROOT=%CD%"

echo ============================================================================
echo  boardwise 安装
echo  仓库：%ROOT%
echo ============================================================================
echo.

if not exist "pyproject.toml" (
  echo [错误] 这里不是 boardwise 仓库根目录：找不到 pyproject.toml
  echo         本脚本要放在仓库的 scripts 文件夹里运行。
  popd
  pause
  exit /b 1
)

rem ---------------------------------------------------------------- 1. Python
echo [1/6] 检查 Python，需要 3.10 或更高 ...
set "PY="
py -3 -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= (3,10) else 9)" >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if not defined PY (
  python -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= (3,10) else 9)" >nul 2>&1
  if not errorlevel 1 set "PY=python"
)
if not defined PY (
  echo.
  echo [错误] 没有找到 Python 3.10 或更高的版本。
  echo        Windows 上的 python 命令有时只是"去应用商店装一个"的跳转，不算已安装。
  echo        请到官网下载安装：https://www.python.org/downloads/windows/
  echo        安装时务必勾上 Add python.exe to PATH；装完关掉本窗口，重新双击本脚本。
  echo        已经装过旧版 Python 的话，装新版即可，旧版不用卸载。
  popd
  pause
  exit /b 1
)
echo        用这个：%PY%
if defined PY %PY% -c "import sys; print('        版本：Python ' + '.'.join(str(n) for n in sys.version_info[:3]))"

rem ---------------------------------------------------------------- 2. venv
echo [2/6] 准备虚拟环境 .venv ...
if exist ".venv\Scripts\python.exe" (
  echo        已经存在，直接复用：%ROOT%\.venv
) else (
  %PY% -m venv .venv
  if errorlevel 1 (
    echo.
    echo [错误] 创建虚拟环境失败。常见原因：
    echo        * 仓库目录没有写权限，或者仓库在只读盘上
    echo        * 这套 Python 是精简版，缺少 venv 模块
    echo        上面 python 命令的报错就是具体原因，处理完再重跑本脚本。
    popd
    pause
    exit /b 1
  )
)
if not exist ".venv\Scripts\python.exe" (
  echo.
  echo [错误] .venv 建了，但找不到 .venv\Scripts\python.exe
  echo        说明这套 Python 不完整，建议换官网安装的正式版重试。
  popd
  pause
  exit /b 1
)
set "VPY=%ROOT%\.venv\Scripts\python.exe"

rem ---------------------------------------------------------------- 3. pip
echo [3/6] 升级 pip ...
"%VPY%" -m pip install --upgrade pip
if errorlevel 1 (
  echo        [提示] 升级 pip 没成功，继续往下走。
  echo               如果下一步安装失败，先解决网络或代理，再重跑本脚本。
)

rem ---------------------------------------------------------------- 4. 安装
echo [4/6] 安装 boardwise：pip install -e .
"%VPY%" -m pip install -e .
if errorlevel 1 (
  echo.
  echo [错误] 安装失败。常见原因：
  echo        * 没联网或要走代理：这一步要从 PyPI 下载 websockets 和构建后端 setuptools，
  echo          离线机器装不上，可以在能联网的机器上下载后再离线安装。
  echo        * 公司网络拦了 pypi.org：换国内镜像再试，例如
  echo          "%VPY%" -m pip install -e . -i https://pypi.tuna.tsinghua.edu.cn/simple
  echo        上面 pip 的最后几行报错就是具体原因。
  popd
  pause
  exit /b 1
)
if not exist ".venv\Scripts\boardwise.exe" (
  echo        [提示] 没生成 boardwise.exe 也没关系，用等效命令就行：
  echo               .venv\Scripts\python.exe -m boardwise.cli
)

rem ---------------------------------------------------------------- 5. dev
echo [5/6] 开发依赖（可选）：跑测试要用 pytest
set "DEV="
set /p "DEV=      装开发依赖吗？按回车装，输入 n 跳过："
if /i "%DEV%"=="n" (
  echo        跳过。以后要跑测试时再敲：
  echo              "%VPY%" -m pip install -e ".[dev]"
) else (
  "%VPY%" -m pip install -e ".[dev]"
  if errorlevel 1 (
    echo        [提示] 开发依赖没装上（多半是网络），不影响使用。
    echo               要跑测试时再敲：.venv\Scripts\python.exe -m pip install -e ".[dev]"
  )
)

rem ---------------------------------------------------------------- 6. doctor
echo [6/6] 跑 boardwise doctor ...
echo.
"%VPY%" -m boardwise.cli doctor
set "DOC=%ERRORLEVEL%"
echo.
if "%DOC%"=="0" (
  echo ============================================================================
  echo  doctor 全绿：命令行这一半已经装好了。
  echo ============================================================================
) else (
  echo ============================================================================
  echo  doctor 退出码 %DOC%：现在有红项。
  echo  首装时这是正常的：daemon 还没起、编辑器还没装扩展。
  echo  每条红项下面都有 → 开头的修复建议，照着做；四步都做完再跑一次 doctor。
  echo ============================================================================
)
echo.
echo 下一步，按顺序：
echo   1. 给编辑器装扩展：立创 EDA Pro - 扩展 - 导入扩展，选中 .eext 文件
echo      * 同事已经给了 boardwise-connector-版本号.eext：直接用那个
echo      * 没有的话：双击 scripts\build-connector.bat 自己打一个，需要 Node.js 20.15 以上
echo      * 导入之后必须完全关掉编辑器再重新打开，不然可能还在跑旧版本
echo   2. 双击 scripts\start-daemon.bat 起 daemon，那个窗口要保持开着
echo      窗口里每 60 秒会打一次连接状态；首次连上会自动配对并打印一条带指纹的公告
echo   3. 复查：  "%VPY%" -m boardwise.cli doctor
echo   4. 第一次审查：
echo      "%VPY%" -m boardwise.cli review 你的工程.epro2 --json report.json --md report.md
echo.
echo 安装说明：docs\install.md      装好之后怎么用：docs\getting-started.md
echo 停止 daemon：scripts\stop-daemon.bat
echo.
popd
pause
exit /b 0
