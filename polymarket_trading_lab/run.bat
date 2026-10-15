@echo off
rem Windows: run.bat [stop]
cd /d "%~dp0"
docker info >nul 2>&1 || (echo Docker is not installed or not running. Start Docker Desktop and retry. & exit /b 1)
if "%1"=="stop" (docker compose down & exit /b)
docker compose up -d --build && echo Dashboard: http://localhost:8000
