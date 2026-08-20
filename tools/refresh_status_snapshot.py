"""Mechanical status-line refresh; no production state mutation."""

from pathlib import Path


path = Path(__file__).resolve().parents[1] / "STUDIO_PRODUCTION_STATUS.md"
lines = path.read_text(encoding="utf-8").splitlines()
replacement = (
    "1. **ECHO//30** — all 30 script/prompt packs complete; Episodes 1–10 released/scheduled "
    "under the legacy cadence; Episode 11 strictly audited and scheduled under the new two-day "
    "cadence; Episodes 12–17 images accepted and queued for automated rendering; Episode 18 has "
    "six of eight frames; Episodes 19–30 remain in the automated creation queue."
)
lines = [replacement if line.startswith("1. **ECHO//30**") else line for line in lines]
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
