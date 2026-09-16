@echo off
chcp 65001 >nul
setlocal
set "REPO=%~dp0"
set "PY=%REPO%.venv\Scripts\python.exe"

rem ---------------------------------------------------------------
rem 机器本地配置（可选，不入 Git）。每行一条 KEY=VALUE，例如：
rem   DEEPSEEK_API_KEY=sk-xxxx
rem   CHEMICAL_TRADE_MATERIALS_ROOT=G:\桌面\化工
rem ---------------------------------------------------------------
if exist "%REPO%.env.local" (
  for /f "usebackq tokens=1,* delims==" %%A in ("%REPO%.env.local") do (
    if not "%%A"=="" set "%%A=%%B"
  )
)

if not defined CHEMICAL_TRADE_MATERIALS_ROOT set "CHEMICAL_TRADE_MATERIALS_ROOT=G:\桌面\化工"
if not defined CHEMICAL_TRADE_DATABASE set "CHEMICAL_TRADE_DATABASE=%REPO%.chroma"
if not defined CHEMICAL_TRADE_MATERIAL_CATALOG set "CHEMICAL_TRADE_MATERIAL_CATALOG=%REPO%materials_catalog.json"
set "PYTHONPATH=%REPO%src"

if not exist "%PY%" (
  echo [错误] 未找到本仓库虚拟环境：%PY%
  echo        请先在本目录执行：
  echo          python -m venv .venv
  echo          .venv\Scripts\python.exe -m pip install -e ".[dev]"
  pause
  exit /b 1
)

if not exist "%CHEMICAL_TRADE_DATABASE%\chroma.sqlite3" (
  echo [错误] 未找到证据索引：%CHEMICAL_TRADE_DATABASE%
  echo        请先建立索引：.venv\Scripts\python.exe -m chemical_trade_copilot.cli rebuild --materials-root "%CHEMICAL_TRADE_MATERIALS_ROOT%" --catalog "%CHEMICAL_TRADE_MATERIAL_CATALOG%" --database "%CHEMICAL_TRADE_DATABASE%" --golden-cases tests\fixtures\golden_retrieval_cases.json
  pause
  exit /b 1
)

if not defined DEEPSEEK_API_KEY (
  echo [提示] 未配置 DEEPSEEK_API_KEY，界面会提示缺少密钥。
  echo        可在 %REPO%.env.local 中写入 DEEPSEEK_API_KEY=...
)

echo 正在启动化工询盘台：http://127.0.0.1:8501
echo 关闭本窗口即停止服务。
echo.
"%PY%" -m streamlit run "%REPO%src\chemical_trade_copilot\streamlit_app.py" --server.address 127.0.0.1 --server.port 8501 --server.headless false --server.fileWatcherType none --browser.gatherUsageStats false

set "APP_EXIT_CODE=%ERRORLEVEL%"
if not "%APP_EXIT_CODE%"=="0" (
  echo.
  echo [错误] 服务退出，代码 %APP_EXIT_CODE%。
  pause
)
exit /b %APP_EXIT_CODE%
