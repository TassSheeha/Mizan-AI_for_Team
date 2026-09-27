@echo off
REM ─── Mizan AI — start Backend (API) + Frontend (dev) together ───────────────
cd /d "%~dp0"

echo [1/2] Starting Backend API on http://localhost:8000 ...
start "Mizan API" cmd /k ".venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --app-dir backend"

echo [2/2] Starting Frontend on http://localhost:5173 ...
start "Mizan Web" cmd /k "cd frontend && npm run dev"

echo.
echo  Backend : http://localhost:8000  (docs at /docs)
echo  Frontend: http://localhost:5173
echo.
echo Default admin: check .env  (ADMIN_EMAIL / ADMIN_PASSWORD)
