@echo off
setlocal
chcp 65001 >nul
set "P03_PROJECT_DIR=%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
  py -3 "%P03_PROJECT_DIR%src\trade.py" serve
) else (
  python "%P03_PROJECT_DIR%src\trade.py" serve
)
if errorlevel 1 pause
