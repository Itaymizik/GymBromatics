"""Development entry point for the FastAPI dashboard/chat service."""

import argparse
from pathlib import Path

import uvicorn

from .api import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", help="Use 0.0.0.0 only inside a container or trusted network")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--dashboards",
        nargs="+",
        type=Path,
        default=[Path("demo_artifacts/squatsample_dashboard.html"), Path("demo_artifacts/squat_test2_dashboard.html")],
    )
    args = parser.parse_args()
    app = create_app(args.dashboards)
    uvicorn.run(app, host=args.host, port=args.port, proxy_headers=True, forwarded_allow_ips="127.0.0.1")


if __name__ == "__main__":
    main()
