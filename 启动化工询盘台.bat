@echo off
chcp 65001 >nul
setlocal
set "REPO=%~dp0"
set "PY=%REPO%.venv\Scripts\python.exe"

rem Machine-local settings live in .env.local and are read by the application itself.
rem See .env.example for the supported keys.

if not defined CHEMICAL_TRADE_DATABASE set "CHEMICAL_TRADE_DATABASE=%REPO%.chroma"
if not defined CHEMICAL_TRADE_MATERIAL_CATALOG set "CHEMICAL_TRADE_MATERIAL_CATALOG=%REPO%materials_catalog.json"
set "PYTHONPATH=%REPO%src"

if not exist "%PY%" goto :no_venv
if not exist "%CHEMICAL_TRADE_DATABASE%\chroma.sqlite3" goto :no_index

echo Starting Chemical Trade Copilot: http://127.0.0.1:8501
echo Close this window to stop the service.
echo.
"%PY%" -m streamlit run "%REPO%src\chemical_trade_copilot\streamlit_app.py" --server.address 127.0.0.1 --server.port 8501 --server.headless false --server.fileWatcherType none --browser.gatherUsageStats false

set "APP_EXIT_CODE=%ERRORLEVEL%"
if not "%APP_EXIT_CODE%"=="0" goto :failed
exit /b 0

:no_venv
echo [ERROR] Virtual environment not found: %PY%
echo         Run these first, in this folder:
echo           python -m venv .venv
echo           .venv\Scripts\python.exe -m pip install -e ".[dev]"
pause
exit /b 1

:no_index
echo [ERROR] Evidence index not found: %CHEMICAL_TRADE_DATABASE%
echo         Build it first, see README.md:
echo           .venv\Scripts\python.exe -m chemical_trade_copilot.cli rebuild --materials-root MATERIALS_ROOT --catalog materials_catalog.json --database .chroma --golden-cases tests\fixtures\golden_retrieval_cases.json
pause
exit /b 1

:failed
echo.
echo [ERROR] Service exited with code %APP_EXIT_CODE%.
pause
exit /b %APP_EXIT_CODE%
