"""python -m hotpath [--show] [--port 8000] [--fake]: serve /shop and the dashboard.
python -m hotpath ci checks.json [--junit out.xml] [--summary out.md]: run browser checks in CI."""
import argparse
import os
import sys

import uvicorn


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "ci":
        from hotpath import ci

        sys.exit(ci.main(sys.argv[2:]))
    ap = argparse.ArgumentParser(prog="hotpath")
    ap.add_argument("--show", action="store_true", help="run the agent's browser headed (headless=False)")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--fake", action="store_true", help="use the scripted fake LLM instead of Claude")
    args = ap.parse_args()
    os.environ["HOTPATH_BASE_URL"] = f"http://127.0.0.1:{args.port}"
    if args.show:
        os.environ["HOTPATH_SHOW"] = "1"
    if args.fake:
        os.environ["HOTPATH_LLM"] = "fake"
    print(f"Hotpath dashboard: http://127.0.0.1:{args.port}/   target site: http://127.0.0.1:{args.port}/shop")
    uvicorn.run("hotpath.server:app", host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
