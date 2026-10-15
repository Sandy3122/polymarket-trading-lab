"""Command-line entry point for local development and operations."""

import argparse

import uvicorn
import asyncio

from .database import init_db
from .worker import PaperMarketWorker


def main() -> None:
    parser = argparse.ArgumentParser(prog="polymarket-lab")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db", help="create database tables")
    serve = sub.add_parser("serve", help="start the local API/dashboard")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    worker = sub.add_parser("paper-worker", help="run the public-data paper-trading worker")
    worker.add_argument("--once", action="store_true", help="discover and process one polling cycle")
    args = parser.parse_args()
    if args.command == "init-db":
        init_db()
        print("Database initialized")
    elif args.command == "serve":
        init_db()
        uvicorn.run("app.api:app", host=args.host, port=args.port, reload=False)
    else:
        init_db()
        worker_instance = PaperMarketWorker()
        if args.once:
            stats = asyncio.run(worker_instance.run_once())
            print(stats)
        else:
            asyncio.run(worker_instance.run_forever())


if __name__ == "__main__":
    main()
