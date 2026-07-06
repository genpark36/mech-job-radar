from __future__ import annotations

import sys

sys.path.insert(0, "src")

from job_radar.cli import main


if __name__ == "__main__":
    raise SystemExit(
        main(["serve", "--host", "127.0.0.1", "--port", "8792", "--no-run-on-start"])
    )
