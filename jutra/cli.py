"""Minimal CLI entrypoint (exposed as `jutra` script)."""

from __future__ import annotations

import sys

import uvicorn


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "run":
        uvicorn.run("jutra.api.main:app", host="0.0.0.0", port=8080)
        return 0
    print("usage: jutra run", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
