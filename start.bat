@echo off
cd /d "%~dp0"

if not exist "venv" (
  echo Setting up virtual environment...
  python3 -m venv venv
  venv\Scripts\pip install -r requirements.txt
)

call venv\Scripts\activate

start "" cmd /c "timeout /t 2 /nobreak >nul && start http://localhost:8000"

echo Server running at http://localhost:8000
echo Press Ctrl+C to stop.
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
