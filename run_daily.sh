#!/usr/bin/env bash
# Simple runner for a local machine / VPS cron.
# Example crontab (posts daily at 6:30am):
#   30 6 * * * /path/to/yt-auto/run_daily.sh >> /path/to/yt-auto/cron.log 2>&1
set -euo pipefail
cd "$(dirname "$0")"

# activate venv if present
if [ -d ".venv" ]; then
  source .venv/bin/activate
fi

python story_main.py
