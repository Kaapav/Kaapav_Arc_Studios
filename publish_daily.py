#!/usr/bin/env python3
"""Retired unsafe entry point.

Kept so an old Windows task cannot accidentally perform an immediate public
release.  Future releases are private/future-scheduled by the studio autopilot.
"""

from __future__ import annotations

import sys


def main() -> None:
    raise RuntimeError(
        "publish_daily.py is retired: immediate public release is forbidden. "
        "Use the QC-gated future scheduler."
    )
    print(result)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"RELEASE BLOCKED: {exc}", file=sys.stderr)
        raise
