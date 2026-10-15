#!/usr/bin/env sh
# Mac/Linux: ./run.sh [stop]
cd "$(dirname "$0")"
command -v docker >/dev/null || { echo "Install Docker first: https://docs.docker.com/get-docker/"; exit 1; }
docker info >/dev/null 2>&1 || { echo "Docker is installed but not running. Start Docker Desktop and retry."; exit 1; }
if [ "$1" = "stop" ]; then docker compose down; exit; fi
docker compose up -d --build && echo "Dashboard: http://localhost:${PORT:-8000}"
