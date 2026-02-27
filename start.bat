@echo off
title Felix Launcher

echo Starting Felix Backend...
start "Backend" cmd /k "cd backend && python -m uvicorn main:app --host 127.0.0.1 --port 8000"

echo Starting Next.js Frontend...
start "Frontend" cmd /k "cd frontend\felix-front && npm run dev -- --hostname 127.0.0.1 --port 3000"

echo Waiting for frontend to be ready...
:wait
timeout /t 2 >nul
curl -s http://127.0.0.1:3000 >nul 2>&1
if %errorlevel% neq 0 goto wait

echo Starting Electron Overlay...
start "Overlay" cmd /k "cd frontend\felix-front && npm run overlay:electron"

echo All services started.
pause
