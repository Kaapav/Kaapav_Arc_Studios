#!/usr/bin/env python3
"""One-click, fail-closed recovery for the KAAPAV ARC control plane."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
REPORT = ROOT / "analytics" / "manual_recovery_status.json"
PAUSE = ROOT / "analytics" / "PAUSE_AUTOPILOT"
TASKS = (
    "KAAPAV ARC Studio Autopilot",
    "KAAPAV ARC Meta Publisher",
    "KAAPAV ARC Dashboard Origin",
    "KAAPAV ARC Dashboard Gateway",
    "KAAPAV ARC Dashboard Health Monitor",
)


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def save(report: dict[str, Any]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    temporary = REPORT.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(REPORT)


def run_step(name: str, arguments: list[str], timeout: int = 300) -> dict[str, Any]:
    print(f"\n[{name}]", flush=True)
    try:
        result = subprocess.run(
            arguments, cwd=ROOT, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
        )
        output = (result.stdout + "\n" + result.stderr).strip()
        if output:
            print(output[-3000:], flush=True)
        return {
            "status": "passed" if result.returncode == 0 else "failed",
            "exit_code": result.returncode,
            "output_tail": output[-3000:],
        }
    except subprocess.TimeoutExpired as exc:
        print("Timed out safely; persisted checkpoints remain intact.", flush=True)
        return {"status": "failed", "error": "timeout", "output_tail": str(exc)[-1000:]}
    except Exception as exc:
        print(f"Failed safely: {type(exc).__name__}: {exc}", flush=True)
        return {"status": "failed", "error_type": type(exc).__name__, "error": str(exc)[:1000]}


def restart_tasks() -> dict[str, Any]:
    quoted = ",".join(f"'{name.replace(chr(39), chr(39) * 2)}'" for name in TASKS)
    script = (
        f"$names=@({quoted}); $result=@(); "
        "foreach($name in $names){"
        "$task=Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue; "
        "if($task){if($task.State -ne 'Running'){Start-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue}; "
        "$fresh=Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue; "
        "$result += [pscustomobject]@{Name=$name;State=[string]$fresh.State}} "
        "else {$result += [pscustomobject]@{Name=$name;State='Missing'}}}; "
        "$result | ConvertTo-Json -Compress"
    )
    step = run_step(
        "Restart silent Windows workers",
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        timeout=60,
    )
    try:
        step["tasks"] = json.loads(step.get("output_tail") or "[]")
    except json.JSONDecodeError:
        pass
    return step


def main() -> int:
    print("=" * 62)
    print("KAAPAV ARC STUDIOS - SAFE RECOVERY")
    print("No QC bypass. No early publish. No credential output.")
    print("=" * 62)
    report: dict[str, Any] = {
        "schema_version": 1,
        "started_at": stamp(),
        "status": "running",
        "fail_closed": True,
        "steps": {},
    }
    save(report)
    if PAUSE.exists():
        report.update({
            "status": "paused_safe",
            "detail": "Global pause is active. Enable automation from the dashboard before recovery.",
            "finished_at": stamp(),
        })
        save(report)
        print("\nGLOBAL PAUSE IS ACTIVE. Nothing was published or restarted.")
        print("Enable automation from the dashboard, then run this shortcut again.")
        return 2
    if not PYTHON.is_file():
        report.update({"status": "failed_closed", "detail": "Project Python runtime is missing", "finished_at": stamp()})
        save(report)
        print("\nProject Python runtime is missing. Recovery stopped safely.")
        return 2

    report["steps"]["universe_audit"] = run_step(
        "Universe and package audit", [str(PYTHON), "-u", "audit_studio_universe.py"], 180,
    )
    report["steps"]["supervisor_refresh"] = run_step(
        "Refresh stale supervisor state without rendering or publishing",
        [str(PYTHON), "-u", "studio_supervisor.py", "--render-limit", "0", "--upload-limit", "0", "--no-network", "--no-google"],
        300,
    )
    report["steps"]["platform_health"] = run_step(
        "YouTube, Facebook and Instagram connection health",
        [str(PYTHON), "-u", "meta_scheduler.py", "--health-only"], 180,
    )
    report["steps"]["due_queue"] = run_step(
        "Process only due, strictly audited releases",
        [str(PYTHON), "-u", "meta_scheduler.py", "--limit", "3"], 900,
    )
    report["steps"]["windows_tasks"] = restart_tasks()
    failed = [name for name, step in report["steps"].items() if step.get("status") != "passed"]
    report.update({
        "status": "healthy" if not failed else "recovery_required",
        "failed_steps": failed,
        "finished_at": stamp(),
        "report_path": str(REPORT),
    })
    save(report)
    print("\n" + "=" * 62)
    if failed:
        print("RECOVERY NEEDS ATTENTION: " + ", ".join(failed))
        print(f"Evidence saved: {REPORT}")
        return 2
    print("RECOVERY COMPLETE: all safety and worker checks passed.")
    print(f"Evidence saved: {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
