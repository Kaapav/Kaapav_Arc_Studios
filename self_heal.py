"""KAAPAV Self-Heal Watchdog.

Watches the control plane for repeated fail-closed failures and applies safe,
backed-up repairs at their root cause. Escalates to ntfy when a repair does not
clear the failure after verification cycles. Never touches pause gates, secrets,
credentials or release actions. Always exits 0.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
from datetime import datetime, timezone

ROOT = pathlib.Path(r"D:\Apps\YT-Auto")
ANALYTICS = ROOT / "analytics"
EVENTS = ANALYTICS / "self_heal_events.jsonl"
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
REPAIR_TOOL = ROOT / "tools" / "repair_episode_titles.py"
NTFY_TOPIC = "kaapav-arc-alerts"
STATE_FILE = ANALYTICS / "self_heal_state.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_json(path: pathlib.Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_json(path: pathlib.Path, data: dict) -> None:
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)


def _append_event(event: dict) -> None:
    event = {"at": _now(), **event}
    try:
        with EVENTS.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        if EVENTS.stat().st_size > 512 * 1024:
            lines = EVENTS.read_text(encoding="utf-8").splitlines()
            EVENTS.write_text("\n".join(lines[-800:]) + "\n", encoding="utf-8")
    except Exception:
        pass


def _title_repair_needed() -> list[tuple[str, str]]:
    failures = _read_json(ANALYTICS / "autopilot_failures.json").get("failures") or {}
    out = []
    for key, failure in failures.items():
        error = str(failure.get("error") or "")
        error_type = str(failure.get("error_type") or "")
        if error_type == "PublishAuditError" and "title" in error.lower():
            out.append((key, error))
    return out


def _run_repair() -> dict:
    proc = subprocess.run(
        [str(PYTHON), str(REPAIR_TOOL), "--scope", "active", "--apply"],
        capture_output=True, text=True, timeout=300,
    )
    try:
        return json.loads(proc.stdout or "{}")
    except Exception:
        return {"parse_error": proc.stdout[:200]}


def _notify(message: str) -> None:
    try:
        subprocess.run(
            ["curl.exe", "-s", "-o", "NUL", "-X", "POST", "-d", message,
             f"https://ntfy.sh/{NTFY_TOPIC}"],
            timeout=15,
        )
    except Exception:
        pass


def main() -> None:
    state = _read_json(STATE_FILE)
    events: list[dict] = []
    supervisor = _read_json(ANALYTICS / "supervisor_state.json")
    certification = _read_json(ANALYTICS / "setup_certification.json")
    supervisor_status = str(supervisor.get("status") or "unknown")

    repairs = _title_repair_needed()
    if repairs:
        keys = ", ".join(k for k, _ in repairs)
        first_key = repairs[0][0]
        previous = state.get("last_title_key")
        last_at = state.get("last_repair_at")
        last_repair = None
        if last_at:
            try:
                last_repair = datetime.fromisoformat(last_at.replace("Z", "+00:00"))
            except ValueError:
                last_repair = None
        stale = not last_repair or (datetime.now(timezone.utc) - last_repair).total_seconds() > 1800
        if previous != first_key or stale:
            report = _run_repair()
            repaired = len(report.get("repaired") or [])
            manual = len(report.get("needs_manual") or [])
            state["last_title_key"] = first_key
            state["last_repair_at"] = _now()
            state["title_repair_cycles"] = 1
            message = (f"self-heal: title repair ran for {keys} "
                       f"(repaired={repaired}, manual={manual})")
            events.append({"event": "title_repair", "failure_keys": keys, **report.get("summary", {})})
            _notify(message)
        else:
            cycles = int(state.get("title_repair_cycles") or 0) + 1
            state["title_repair_cycles"] = cycles
            escalated = set(state.get("escalated_keys") or [])
            if cycles >= 3 and first_key not in escalated:
                escalated.add(first_key)
                state["escalated_keys"] = sorted(escalated)
                events.append({"event": "title_repair_stuck", "failure_key": first_key, "error": repairs[0][1][:300]})
                _notify(f"self-heal ESCALATION: {first_key} still failing after repair: {repairs[0][1][:200]}")
    else:
        state["last_title_key"] = None
        state["last_repair_at"] = None
        state["title_repair_cycles"] = 0
        state["escalated_keys"] = []

    cert_failed = certification.get("failed_checks") or []
    known_drift = {"five_tab_dashboard_and_retention_upgrade_path",
                   "unit_and_safety_tests",
                   "windows_scheduler_recovery_and_pause_path",
                   "youtube_remote_contract_reconciliation"}
    unknown_fails = [c for c in cert_failed if c not in known_drift]
    if unknown_fails:
        events.append({"event": "certification_unknown_failures", "checks": unknown_fails})
        _notify(f"self-heal: certification has unknown failed checks: {unknown_fails}")

    if events:
        for event in events:
            _append_event(event)
    state["checked_at"] = _now()
    state["supervisor_status"] = supervisor_status
    state["cert_failed_count"] = len(cert_failed)
    _write_json(STATE_FILE, state)


if __name__ == "__main__":
    main()
    sys.exit(0)