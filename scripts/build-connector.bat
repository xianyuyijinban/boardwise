@echo off
chcp 936 >nul 2>&1
rem ============================================================================
rem  打包编辑器扩展 .eext
rem  流程：npm ci 装依赖 - npm run package 构建并打包 - 打印产物路径
rem  只有自己从源码构建才需要本脚本；同事已经给了 .eext 的话直接用，不用跑它。
rem  需要 Node.js 20.15 以上：打包脚本用到 node:zlib 的 crc32，更低的版本没有这个接口。
rem  本文件是 ANSI/GBK 编码，第 2 行切到 936；两行都要留着，否则中文会乱。
rem ============================================================================
setlocal EnableExtensions
title boardwise 构建编辑器扩展

set "ROOT=%~dp0.."
pushd "%ROOT%" >nul 2>&1
if errorlevel 1 (
  echo [错误] 进不去仓库目录：%ROOT%
  pause
  exit /b 1
)
set "ROOT=%CD%"

if not exist "connector\package.json" (
  echo [错误] 找不到 connector\package.json
  echo         请在完整仓库里运行本脚本，当前目录：%ROOT%
  popd
  pause
  exit /b 1
)

echo ============================================================================
echo  构建 boardwise 编辑器扩展
echo ============================================================================
echo.

rem ---------------------------------------------------------------- 1. Node
echo [1/3] 检查 Node.js ...
set "NODE_MAJOR="
for /f "tokens=1 delims=." %%V in ('node --version 2^>nul') do set "NODE_MAJOR=%%V"
set "NODE_MAJOR=%NODE_MAJOR:v=%"
if not defined NODE_MAJOR (
  echo.
  echo [错误] 没有找到 node 命令，需要 Node.js 才能构建扩展。
  echo        请到官网下载 LTS 版安装：https://nodejs.org/zh-cn/download
  echo        装完关掉本窗口，重新双击本脚本。
  popd
  pause
  exit /b 1
)
echo        node 大版本：%NODE_MAJOR%，需要 20 以上
if %NODE_MAJOR% LSS 20 (
  echo.
  echo [错误] Node.js 版本太低。
  echo        打包脚本用到 node:zlib 的 crc32，需要 Node.js 20.15 以上，建议直接装 LTS。
  echo        下载：https://nodejs.org/zh-cn/download
  popd
  pause
  exit /b 1
)

rem ---------------------------------------------------------------- 2. npm ci
echo [2/3] 装依赖：npm ci ...
pushd "connector"
call npm ci --no-audit --no-fund
if errorlevel 1 (
  echo.
  echo [错误] npm ci 失败。常见原因：
  echo        * 没联网，或要走代理：这一步要从 npmjs.org 下载 esbuild、typescript
  echo        * 公司内网：可以先换镜像 npm config set registry https://registry.npmmirror.com
  echo        * package-lock.json 与 package.json 不同步：在 connector 目录跑一次 npm install 刷新锁文件
  echo        上面 npm 的最后几行报错就是具体原因。
  popd
  popd
  pause
  exit /b 1
)

rem ---------------------------------------------------------------- 3. package
echo [3/3] 构建并打包：npm run package ...
call npm run package
if errorlevel 1 (
  echo.
  echo [错误] 构建失败。上面 npm 的报错就是原因。
  echo        先确认 Node.js 版本 20.15 以上、依赖已经装全，再重试。
  popd
  popd
  pause
  exit /b 1
)

set "LATEST="
for /f "delims=" %%F in ('dir /b /o-d "boardwise-connector-*.eext" 2^>nul') do if not defined LATEST set "LATEST=%CD%\%%F"
echo.
echo 产物目录：%CD%
if defined LATEST (
  echo 最新产物：%LATEST%
) else (
  echo [警告] 没找到 boardwise-connector-*.eext，请检查上面的 npm 输出。
)
echo.
echo 下一步：立创 EDA Pro 里点 扩展 - 导入扩展，选中上面那个 .eext，
echo         然后完全关闭编辑器再重新打开。已经有同事给的 .eext 就不必跑本脚本。
echo.
popd
popd
pause
exit /b 0
