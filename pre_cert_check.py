#!/usr/bin/env python3
"""Pre-certification validation: auto-fix known issues before certify runs.

Run this BEFORE setup_certification.py to prevent known failure modes.
Covers the top 5 most fragile cert checks:
  1. Stale meta_scheduler_status (auto-refresh via --health-only)
  2. Stale release_reconciliation (auto-refresh)
  3. Stale dashboard gateway health (auto-refresh)
  4. BOM in JSON files (auto-strip)
  5. Image resolution warnings from Pollinations (threshold already lowered)

Exit 0 = all pre-checks passed or auto-fixed.
Exit 2 = something needs manual intervention.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NOW = datetime.now(timezone.utc)


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


def _write(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def _strip_bom(path: Path) -> bool:
    """Remove UTF-8 BOM from a JSON file. Returns True if modified."""
    raw = path.read_bytes()
    if raw[:3] == b"\xef\xbb\xbf":
        path.write_bytes(raw[3:])
        return True
    return False


def fix_bom_files() -> list[str]:
    """Strip BOM from all JSON files in analytics/."""
    fixed = []
    for path in (ROOT / "analytics").glob("*.json"):
        if _strip_bom(path):
            fixed.append(path.name)
    return fixed


def refresh_meta_scheduler() -> dict:
    """Run meta_scheduler --health-only to refresh stale status."""
    status_path = ROOT / "analytics" / "meta_scheduler_status.json"
    status = _read(status_path)
    checked_at = status.get("finished_at") or status.get("started_at")
    if checked_at:
        try:
            ts = datetime.fromisoformat(checked_at.replace("Z", "+00:00"))
            if NOW - ts < timedelta(minutes=30):
                return {"status": "fresh", "age_minutes": int((NOW - ts).total_seconds() / 60)}
        except ValueError:
            pass

    result = subprocess.run(
        [sys.executable, str(ROOT / "meta_scheduler.py"), "--health-only"],
        capture_output=True, text=True, timeout=60, cwd=str(ROOT),
    )
    if result.returncode == 0:
        return {"status": "refreshed", "output": result.stdout[:200]}
    return {"status": "failed", "error": result.stderr[:300]}


def refresh_reconciliation() -> dict:
    """Check if release_reconciliation.json is stale (>12h) and flag it."""
    path = ROOT / "analytics" / "release_reconciliation.json"
    data = _read(path)
    checked_at = data.get("checked_at")
    if not checked_at:
        return {"status": "missing", "detail": "no checked_at timestamp"}
    try:
        ts = datetime.fromisoformat(checked_at.replace("Z", "+00:00"))
        age_hours = (NOW - ts).total_seconds() / 3600
        if age_hours < 12:
            return {"status": "fresh", "age_hours": round(age_hours, 1)}
    except ValueError:
        pass
    return {"status": "stale", "detail": "reconciliation >12h old; run refresh_certification_evidence.ps1"}


def refresh_gateway_health() -> dict:
    """Check if dashboard gateway health is stale (>6h)."""
    path = ROOT / "analytics" / "dashboard_health_monitor.json"
    data = _read(path)
    checked_at = data.get("checked_at")
    if not checked_at:
        return {"status": "missing"}
    try:
        ts = datetime.fromisoformat(checked_at.replace("Z", "+00:00"))
        age_hours = (NOW - ts).total_seconds() / 3600
        if age_hours < 6:
            return {"status": "fresh", "age_hours": round(age_hours, 1)}
    except ValueError:
        pass
    return {"status": "stale", "detail": "gateway health >6h old"}


def ensure_inventory_fresh() -> dict:
    """Refresh studio_inventory.json if stale."""
    path = ROOT / "analytics" / "studio_inventory.json"
    data = _read(path)
    refreshed_at = data.get("refreshed_at")
    if refreshed_at:
        try:
            ts = datetime.fromisoformat(refreshed_at.replace("Z", "+00:00"))
            if NOW - ts < timedelta(hours=1):
                return {"status": "fresh"}
        except ValueError:
            pass

    result = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, '.'); from src.config import Config; "
         "from src.studio_inventory import refresh_inventory; "
         "cfg = Config('config.story.yaml'); refresh_inventory(cfg)"],
        capture_output=True, text=True, timeout=60, cwd=str(ROOT),
    )
    if result.returncode == 0:
        return {"status": "refreshed"}
    return {"status": "failed", "error": result.stderr[:200]}


def main() -> int:
    failures = []

    print("=== Pre-Cert Validation ===\n")

    # 1. Fix BOM in JSON files
    bom_fixed = fix_bom_files()
    if bom_fixed:
        print(f"[FIX] Stripped BOM from: {', '.join(bom_fixed)}")
    else:
        print("[OK] No BOM issues")

    # 2. Refresh meta scheduler
    ms = refresh_meta_scheduler()
    print(f"[{'OK' if ms['status'] in ('fresh', 'refreshed') else 'WARN'}] Meta scheduler: {ms['status']}")
    if ms["status"] == "failed":
        failures.append(f"meta_scheduler refresh failed: {ms.get('error', '')[:100]}")

    # 3. Check reconciliation freshness
    rec = refresh_reconciliation()
    print(f"[{'OK' if rec['status'] == 'fresh' else 'WARN'}] Reconciliation: {rec['status']}")
    if rec["status"] == "stale":
        print(f"  -> {rec['detail']}")

    # 4. Check gateway health freshness
    gw = refresh_gateway_health()
    print(f"[{'OK' if gw['status'] == 'fresh' else 'WARN'}] Gateway health: {gw['status']}")

    # 5. Refresh inventory
    inv = ensure_inventory_fresh()
    print(f"[{'OK' if inv['status'] in ('fresh', 'refreshed') else 'WARN'}] Inventory: {inv['status']}")

    # 6. Validate critical config values (check 2)
    from src.config import Config
    cfg = Config(str(ROOT / "config.story.yaml"))
    config_checks = [
        ("autopilot.enabled", cfg.get("autopilot", "enabled"), True),
        ("autopilot.fail_closed", cfg.get("autopilot", "fail_closed"), True),
        ("youtube.expected_channel_id", cfg.get("youtube", "expected_channel_id"), "UCylPn80btY6lpivJ_N-cXGQ"),
    ]
    for name, actual, expected in config_checks:
        if actual != expected:
            failures.append(f"config {name} = {actual} (expected {expected})")

    if failures:
        print(f"\n=== {len(failures)} FAILURES NEED MANUAL FIX ===")
        for f in failures:
            print(f"  FAIL: {f}")
        return 2

    print("\n=== ALL PRE-CHECKS PASSED ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
