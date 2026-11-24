import argparse
import os
import sys

from dashboard import web


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m dashboard.serve",
        description=(
            "Serve the factory metrics page. It reads only from the Postgres "
            "database named by DATABASE_URL and never calls Anthropic. "
            "Port comes from PORT (default 8000), host from HOST "
            "(default 127.0.0.1; use 0.0.0.0 to listen on every interface)."
        ),
        epilog="Example: DATABASE_URL=postgresql:///dashboard PORT=8000 uv run --project v2 python -m dashboard.serve",
    )
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    args = parser.parse_args(argv)
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL is required", file=sys.stderr)
        return 2
    server = web.make_server(url, args.host, args.port)
    print(f"serving on http://{args.host}:{server.server_address[1]}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
