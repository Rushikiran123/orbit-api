"""orbit CLI: run the dev server."""

import argparse


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="orbit")
    sub = parser.add_subparsers(dest="command", required=True)
    p_serve = sub.add_parser("serve", help="run the API server")
    p_serve.add_argument("--host", default="0.0.0.0")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.add_argument("--reload", action="store_true")
    args = parser.parse_args(argv)

    if args.command == "serve":
        import uvicorn

        uvicorn.run("orbit.main:app", host=args.host, port=args.port, reload=args.reload)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
