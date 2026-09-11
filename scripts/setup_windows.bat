@echo off
setlocal
cd /d "%~dp0\.."

where py >nul 2>nul || (echo Python launcher not found. Install Python 3.12. & exit /b 1)
if not exist ".venv\Scripts\python.exe" py -3.12 -m venv .venv || exit /b 1
call ".venv\Scripts\activate.bat"
python scripts\generate_env.py || exit /b 1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt || exit /b 1
for /f "usebackq eol=# tokens=1,* delims==" %%A in (".env") do set "%%A=%%B"
python autotrade.py validate || exit /b 1
python -m freqtrade --version || exit /b 1
python -m unittest discover -s tests -v || exit /b 1
echo Setup and safety checks passed.
