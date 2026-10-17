@echo off
rem ============================================================================
rem  install-hooks.bat - point git at the tracked hook directory (.githooks).
rem
rem  Why this script exists: the hooks were a bare copy in .git\hooks, which is
rem  not in the repository. Nothing a clone gets, nothing a reviewer can see,
rem  nothing that survives a fresh clone, and a second copy to keep in sync --
rem  `git config core.hooksPath` is one line and ends the whole problem (193 B.1).
rem
rem  What it does, in order:
rem    1. checks this is a git checkout with the tracked hooks present;
rem    2. sets core.hooksPath = .githooks (in this repository's local config);
rem    3. migrates the legacy .git\hooks\pre-commit: the bare copy of the same
rem       guard. It is deleted **to the recycle bin** (never `del`) once it is
rem       byte-identical to .githooks\pre-commit, or when it has the legacy
rem       guard's signature (calls check_repo_hygiene.py with --staged). Anything
rem       else is a hook somebody wrote, and is left alone and reported.
rem
rem  Idempotent: run it twice. The second run finds no legacy hook and just
rem  re-asserts the config.
rem
rem  POSIX note: a clone that checks these hooks out needs them executable
rem  (`chmod +x .githooks/*`). On Windows git runs them through its own sh and
rem  the bit does not exist. This batch file cannot do it for you.
rem
rem  ASCII only on purpose: .bat files are run by cmd.exe with the console code
rem  page (this repository's other scripts are GBK for that reason), and an
rem  encoding mistake here would garble the one line that tells you whether the
rem  guards are installed.
rem ============================================================================
setlocal EnableExtensions
title boardwise install-hooks

set "ROOT=%~dp0.."
pushd "%ROOT%" >nul 2>&1
if errorlevel 1 (
  echo [error] cannot enter the repository root: %ROOT%
  pause
  exit /b 1
)
set "ROOT=%CD%"

echo ============================================================================
echo  boardwise install-hooks
echo  repo: %ROOT%
echo ============================================================================

if not exist "pyproject.toml" (
  echo [error] pyproject.toml not found here - run this script from the repo's
  echo         scripts\ directory.
  popd
  pause
  exit /b 1
)

if not exist ".githooks\pre-commit" (
  echo [error] .githooks\pre-commit is missing - the tracked hooks are not here,
  echo         so pointing git at .githooks would disable the guards entirely.
  popd
  pause
  exit /b 1
)

git rev-parse --git-dir >nul 2>&1
if errorlevel 1 (
  echo [error] this directory is not a git checkout ^(git rev-parse --git-dir failed^).
  popd
  pause
  exit /b 1
)

echo [1/2] git config core.hooksPath .githooks
git config core.hooksPath .githooks
if errorlevel 1 (
  echo [error] git config failed - the hooks are NOT installed.
  popd
  pause
  exit /b 1
)
for /f "delims=" %%p in ('git config core.hooksPath') do echo        core.hooksPath = %%p
echo        installed: pre-commit, commit-msg, pre-push

echo [2/2] migrating the legacy bare hook ^(if any^)
set "OLD=.git\hooks\pre-commit"
if not exist "%OLD%" (
  echo        no legacy hook at %OLD% - nothing to migrate ^(this is also what a
  echo        second run of this script looks like^).
  goto :done
)

fc /b "%OLD%" ".githooks\pre-commit" >nul 2>&1
if not errorlevel 1 (
  echo        %OLD% is byte-identical to .githooks\pre-commit.
  call :recycle "%OLD%"
  goto :done
)

findstr /c:"check_repo_hygiene.py" "%OLD%" | findstr /c:"--staged" >nul 2>&1
if not errorlevel 1 (
  echo        %OLD% carries the legacy guard signature ^(check_repo_hygiene.py --staged^).
  call :recycle "%OLD%"
  goto :done
)

echo        [keep] %OLD% differs from .githooks\pre-commit and is not the legacy
echo               guard: left in place. It is inert while core.hooksPath is set,
echo               but it is yours to delete.
goto :done

:recycle
powershell -NoProfile -Command "Add-Type -AssemblyName Microsoft.VisualBasic; [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile((Resolve-Path '%~1').Path,'OnlyErrorDialogs','SendToRecycleBin')" >nul 2>&1
if errorlevel 1 (
  echo        [warn] could not move %~1 to the recycle bin - leaving it alone.
  echo               ^(It is inert while core.hooksPath=.githooks.^)
) else (
  echo        [ok]   %~1 moved to the recycle bin ^(the .githooks copy is the live one now^).
)
exit /b 0

:done
echo.
echo done. Commits and pushes are now scanned by:
echo   .githooks\pre-commit   staged content + sensitive words
echo   .githooks\commit-msg   the commit message
echo   .githooks\pre-push     outgoing commit messages + diff
echo Uninstall: git config --unset core.hooksPath
echo.
popd
pause
exit /b 0
