#!/usr/bin/env python3
"""Zero-touch, fail-closed KAAPAV ARC production and release controller.

Normal operation: refresh evidence, learn, reconcile the 14-day buffer, render
accepted assets, audit exact bytes, and future-schedule private uploads. Missing
creative assets are queued for the Codex production worker; quality is never
lowered to fill a slot.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.config import Config, ROOT
from src import growth_learning, meta_platform, performance, platform_control, story_factory, studio_inventory, youtube_analytics, youtube_playlists
from src.release_audit import PublishAuditError, run_publish_audit


LOCK_PATH = ROOT / "analytics" / "autopilot.lock"
STATE_PATH = ROOT / "analytics" / "autopilot_state.json"
EVENTS_PATH = ROOT / "analytics" / "autopilot_events.jsonl"
FAILURES_PATH = ROOT / "analytics" / "autopilot_failures.json"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def event(kind: str, **fields: Any) -> None:
    payload = {
        "at": _now().isoformat().replace("+00:00", "Z"), "event": kind, **fields,
    }
    EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with EVENTS_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _pid_alive(pid: Any) -> bool:
    try:
        numeric = int(pid)
        if numeric <= 0:
            return False
        os.kill(numeric, 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


class RunLock:
    def __enter__(self):
        LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        existing = _read(LOCK_PATH)
        if existing:
            try:
                created = datetime.fromisoformat(str(existing.get("created_at")).replace("Z", "+00:00"))
            except ValueError:
                created = _now() - timedelta(days=1)
            if _pid_alive(existing.get("pid")) and _now() - created < timedelta(hours=4):
                raise RuntimeError(f"Autopilot already running as PID {existing.get('pid')}")
            event(
                "stale_lock_recovered", previous_pid=existing.get("pid"),
                previous_pid_alive=_pid_alive(existing.get("pid")),
            )
        _write(LOCK_PATH, {
            "pid": os.getpid(), "created_at": _now().isoformat().replace("+00:00", "Z")
        })
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            current = _read(LOCK_PATH)
            if current.get("pid") == os.getpid():
                LOCK_PATH.unlink(missing_ok=True)
        except OSError:
            pass


def _metadata_for(item: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    output = Path(item["output_root"])
    metadata_path = output / "metadata.json"
    metadata = _read(metadata_path)
    manifest_path = item.get("manifest_path")
    if manifest_path and Path(manifest_path).exists():
        manifest = _read(Path(manifest_path))
        live_title = str(manifest.get("title") or "")
        from src.title_policy import validate_episode_title, title_opening_overlap
        opening = " ".join(
            str(scene.get("text") or scene.get("caption") or "")
            for scene in (manifest.get("scenes") or [])[:2] if isinstance(scene, dict)
        )
        if (live_title and not validate_episode_title(live_title)
                and title_opening_overlap(live_title, opening).get("passed")):
            if metadata.get("title") != live_title:
                metadata["title"] = live_title
                _write(metadata_path, metadata)
            script_path = output / "script.json"
            if script_path.exists():
                script = _read(script_path)
                if script.get("title") != live_title:
                    script["title"] = live_title
                    _write(script_path, script)
    metadata["thumbnail_path"] = str(output / "thumbnail.jpg")
    metadata.setdefault("release_kind", "short")
    metadata.setdefault("series_id", item["series_id"])
    metadata.setdefault("episode", item["episode"])
    metadata.setdefault("episode_id", item.get("episode_id"))
    return metadata_path, metadata


def _failure_key(item: dict[str, Any], action: str) -> str:
    return f"{item.get('series_id')}:{item.get('episode')}:{action}"


def _can_retry(item: dict[str, Any], action: str) -> bool:
    failure = (_read(FAILURES_PATH).get("failures") or {}).get(_failure_key(item, action), {})
    retry_at = failure.get("retry_at")
    if not retry_at:
        return True
    try:
        return _now() >= datetime.fromisoformat(retry_at.replace("Z", "+00:00"))
    except ValueError:
        return True


def _record_failure(item: dict[str, Any], action: str, exc: Exception) -> None:
    state = _read(FAILURES_PATH) or {"schema_version": 1, "failures": {}}
    failures = state.setdefault("failures", {})
    key = _failure_key(item, action)
    attempts = int((failures.get(key) or {}).get("attempts") or 0) + 1
    delay_minutes = min(360, 15 * (2 ** min(attempts - 1, 5)))
    failures[key] = {
        "attempts": attempts,
        "last_at": _now().isoformat().replace("+00:00", "Z"),
        "retry_at": (_now() + timedelta(minutes=delay_minutes)).isoformat().replace("+00:00", "Z"),
        "error_type": type(exc).__name__,
        "error": str(exc)[:500],
        "state": "quarantined_retry" if attempts < 5 else "quarantined_long_backoff",
    }
    _write(FAILURES_PATH, state)
    event("task_failed", key=key, attempts=attempts, error_type=type(exc).__name__)


def _clear_failure(item: dict[str, Any], action: str) -> None:
    state = _read(FAILURES_PATH)
    failures = state.get("failures") or {}
    if failures.pop(_failure_key(item, action), None) is not None:
        state["failures"] = failures
        _write(FAILURES_PATH, state)


def _describe_failures(failed: list[dict[str, Any]], hard: list[dict[str, Any]] | None = None, *,
                       deferred: list[dict[str, Any]] | None = None) -> str:
    parts = []
    for f in (failed or []):
        parts.append(f"{f.get('series_id')} ep{f.get('episode')}: {f.get('error_type')} ({f.get('error', '')[:90]})")
    if deferred:
        eps = ", ".join(f"{f.get('series_id')} ep{f.get('episode')}" for f in deferred)
        parts.append(f"cooldown: {eps} title auto-repair pending (self-heal); uploads next cycle")
    return "; ".join(parts) if parts else "none"


def refresh_metrics(cfg, *, no_google: bool) -> dict[str, Any]:
    summary, rows = performance.collect(cfg)
    from src import release_ledger
    legacy = release_ledger.adopt_legacy_echo(rows, cfg)
    contract_backfills = release_ledger.backfill_strict_contracts(cfg)
    rows = release_ledger.enrich_rows(rows)
    current, history_path, history = performance.save_local(rows, channel_id=summary["channel_id"])
    detailed = youtube_analytics.collect(cfg, rows)
    reconciliation = release_ledger.reconcile_remote(rows)
    learning = growth_learning.refresh_learning(
        cfg, rows, detailed.get("videos", {}), history_rows=history,
    )
    growth_learning.write_production_directives()
    google_url = None
    if not no_google:
        try:
            google_url = performance.sync_google_sheet(cfg, rows, history, summary=summary)
        except Exception as exc:
            event("google_sheet_degraded", error_type=type(exc).__name__)
    performance.write_status(summary, current, history_path, google_url)
    playlist_recovery = {"status": "not_attempted"}
    try:
        from src.upload import _get_service
        playlist_recovery = {"status": "ok", **youtube_playlists.reconcile(_get_service(cfg))}
    except Exception as exc:
        playlist_recovery = {"status": "recovery_required", "error_type": type(exc).__name__}
    return {
        "summary": summary, "rows": rows, "learning_observations": len(learning["observations"]),
        "retention_status": detailed.get("status"), "google_sheet": google_url,
        "release_reconciliation": reconciliation.get("status"),
        "legacy_release_adoption": len(legacy.get("adopted") or []),
        "strict_contract_backfills": contract_backfills,
        "playlist_recovery": playlist_recovery,
    }


def _terminate_process_tree(process: subprocess.Popen) -> None:
    """Terminate only the isolated worker tree created by this controller."""
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True, text=True, timeout=30,
        )
    else:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)


def _run_render_worker(cfg, item: dict[str, Any]) -> Path:
    """Render out-of-process so a dead encoder cannot stall the supervisor."""
    manifest = Path(item["manifest_path"])
    if item["series_id"] == "echo30":
        command = [sys.executable, "-u", str(ROOT / "render_echo_v2_cute.py"), str(manifest)]
    else:
        command = [
            sys.executable, "-u", str(ROOT / "studio_manual_pipeline.py"),
            "render", str(manifest),
        ]
    output_root = Path(item["output_root"])
    output_root.mkdir(parents=True, exist_ok=True)
    log_path = output_root / "render_worker.log"
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    timeout = int(cfg.get("autopilot", "render_timeout_minutes", default=45)) * 60
    with log_path.open("w", encoding="utf-8", buffering=1) as log_handle:
        log_handle.write(
            f"worker_started={_now().isoformat().replace('+00:00', 'Z')} "
            f"timeout_minutes={timeout // 60}\n"
        )
        log_handle.flush()
        process = subprocess.Popen(
            command, cwd=ROOT, stdout=log_handle, stderr=subprocess.STDOUT,
            text=True, creationflags=creationflags,
            start_new_session=os.name != "nt",
        )
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            _terminate_process_tree(process)
            process.wait(timeout=30)
            log_handle.write("worker_terminated=render_timeout\n")
            raise RuntimeError(f"Render worker exceeded {timeout // 60} minutes and was terminated") from exc
    if process.returncode != 0:
        tail = log_path.read_text(encoding="utf-8", errors="replace")[-1200:].replace("\n", " ")
        raise RuntimeError(f"Render worker failed with exit code {process.returncode}: {tail}")
    video_path = output_root / "video.mp4"
    if not video_path.exists():
        raise RuntimeError("Render worker exited successfully without video.mp4")
    return video_path


def _active_episodes(cfg, inventory: dict[str, Any]) -> list[dict[str, Any]]:
    active_sequence = int(inventory.get("active_series_sequence") or 1)
    policy_start = int(cfg.get("autopilot", "policy_applies_from_episode", default=11))
    active = [
        item for item in inventory["episodes"]
        if int(item.get("sequence") or 0) == active_sequence
        and not (active_sequence == 1 and int(item.get("episode") or 0) < policy_start)
    ]
    return sorted(active, key=lambda item: int(item["episode"]))


def _schedule_candidates(cfg, inventory: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    candidates = []
    for item in _active_episodes(cfg, inventory):
        if item.get("state") in {"public", "scheduled"}:
            continue
        if item.get("state") in {"strict_audit_passed", "strict_audit_pending", "private_uploaded"}:
            candidates.append(item)
            if len(candidates) >= max(0, limit):
                break
            continue
        # Never release around a missing/QC-failed earlier chapter.
        break
    return candidates


def _render_candidates(cfg, inventory: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    if int(inventory.get("shortage") or 0) <= 0:
        return []
    active = [item for item in _active_episodes(cfg, inventory) if item.get("state") != "public"]
    window = active[: int(inventory.get("target_ready_shorts") or 7)]
    candidates = []
    for item in window:
        if item.get("state") in {"scheduled", "strict_audit_passed", "private_uploaded"}:
            continue
        if item.get("state") == "render_ready":
            candidates.append(item)
            if len(candidates) >= max(0, limit):
                break
            continue
        # Do not spend render time beyond an earlier creative/QC failure.
        break
    return candidates


def render_ready(cfg, inventory: dict[str, Any], limit: int) -> dict[str, list[dict[str, Any]]]:
    completed = []
    failed = []
    shortage = int(inventory.get("shortage") or 0)
    if shortage <= 0:
        return {"completed": completed, "failed": failed}
    candidates = _render_candidates(cfg, inventory, min(limit, shortage))
    for item in candidates[: max(0, min(limit, shortage))]:
        if not _can_retry(item, "render"):
            failed.append({
                "series_id": item.get("series_id"), "episode": item.get("episode"),
                "error_type": "BackoffActive", "error": "waiting for persisted render retry_at",
            })
            continue
        try:
            video_path = _run_render_worker(cfg, item)
            metadata_path, metadata = _metadata_for({
                **item, "output_root": str(Path(video_path).parent),
            })
            report = run_publish_audit(cfg, Path(video_path), metadata)
            metadata.update({
                "status": "strict_audit_passed", "uploaded": False,
                "audit_id": report["audit_id"],
            })
            _write(metadata_path, metadata)
            _clear_failure(item, "render")
            completed.append({"series_id": item["series_id"], "episode": item["episode"]})
            event("render_and_audit_passed", series_id=item["series_id"], episode=item["episode"], audit_id=report["audit_id"])
        except Exception as exc:
            _record_failure(item, "render", exc)
            failed.append({
                "series_id": item.get("series_id"), "episode": item.get("episode"),
                "error_type": type(exc).__name__, "error": str(exc)[:300],
            })
    return {"completed": completed, "failed": failed}


def schedule_ready(cfg, inventory: dict[str, Any], limit: int) -> dict[str, list[dict[str, Any]]]:
    from src.upload import schedule_video, upload_video

    completed = []
    failed = []
    deferred = []
    candidates = _schedule_candidates(cfg, inventory, limit)
    existing = [item.get("publish_at") for item in inventory["episodes"] if item.get("publish_at")]
    slots = studio_inventory.next_short_slots(existing, min(limit, len(candidates)), cfg)
    for item, slot in zip(candidates, slots):
        if not _can_retry(item, "schedule"):
            deferred.append({
                "series_id": item.get("series_id"), "episode": item.get("episode"),
                "error_type": "BackoffActive", "error": "waiting for persisted schedule retry_at",
                "deferred": "backoff cooldown active; retries after retry_at",
            })
            continue
        metadata_path, metadata = _metadata_for(item)
        try:
            existing_id = metadata.get("youtube_id") or _read(Path(item["output_root"]) / "upload_result.json").get("id")
            if existing_id:
                result = schedule_video(
                    cfg, str(existing_id), slot,
                    video_path=Path(item["video_path"]), meta=metadata,
                )
                result["url"] = metadata.get("youtube_url") or f"https://youtu.be/{existing_id}"
            else:
                result = upload_video(
                    cfg, Path(item["video_path"]), metadata,
                    privacy_override="private", publish_at=slot,
                )
            if not result.get("thumbnail_set") or not result.get("schedule_confirmed"):
                metadata.update({
                    "status": "private_uploaded", "uploaded": True,
                    "youtube_id": result["id"], "youtube_url": result["url"],
                    "publish_at": None, "audit_id": result.get("audit_id"),
                })
                _write(metadata_path, metadata)
                _write(Path(item["output_root"]) / "upload_result.json", result)
                event(
                    "upload_held_private", series_id=item["series_id"], episode=item["episode"],
                    reason=result.get("status") or "remote_release_contract_not_confirmed",
                )
                failed.append({
                    "series_id": item.get("series_id"), "episode": item.get("episode"),
                    "error_type": "RemoteContractHeld", "error": result.get("status"),
                })
                continue
            metadata.update({
                "status": "scheduled", "uploaded": True,
                "youtube_id": result["id"], "youtube_url": result["url"],
                "publish_at": slot, "audit_id": result.get("audit_id"),
            })
            _write(metadata_path, metadata)
            _write(Path(item["output_root"]) / "upload_result.json", result)
            _clear_failure(item, "schedule")
            completed.append({"series_id": item["series_id"], "episode": item["episode"], "publish_at": slot})
            event("future_scheduled", series_id=item["series_id"], episode=item["episode"], publish_at=slot, audit_id=result.get("audit_id"))
        except Exception as exc:
            _record_failure(item, "schedule", exc)
            if type(exc).__name__ == "PublishAuditError" and "title" in str(exc).lower():
                deferred.append({
                    "series_id": item.get("series_id"), "episode": item.get("episode"),
                    "error_type": type(exc).__name__, "error": str(exc)[:300],
                    "deferred": "auto title repair (self-heal); uploads on next cycle",
                })
            else:
                failed.append({
                    "series_id": item.get("series_id"), "episode": item.get("episode"),
                    "error_type": type(exc).__name__, "error": str(exc)[:300],
                })
    return {"completed": completed, "failed": failed, "deferred": deferred}


def build_and_schedule_compilation(cfg, inventory: dict[str, Any]) -> dict[str, Any] | None:
    """Create the next complete five-episode block and future-schedule it on a weekend."""
    from build_echo_compilation import build
    from src.upload import schedule_video, upload_video

    echo = {int(item["episode"]): item for item in inventory["episodes"] if item["series_id"] == "echo30"}
    for start in (11, 16, 21, 26):
        end = start + 4
        block = [echo.get(number) for number in range(start, end + 1)]
        if any(item is None or item.get("state") not in {"scheduled", "public"} for item in block):
            continue
        output = ROOT / "output" / "story" / f"echo30-compilation-episodes{start:02d}-{end:02d}"
        metadata_path = output / "metadata.json"
        metadata = _read(metadata_path)
        if metadata.get("status") == "scheduled":
            continue
        if not (output / "video.mp4").exists() or metadata.get("status") not in {"strict_audit_passed", "private_uploaded"}:
            build(start, end)
            metadata = _read(metadata_path)
        last_publish = max(str(item.get("publish_at")) for item in block if item.get("publish_at"))
        slot = studio_inventory.next_compilation_slot(last_publish, cfg)
        metadata["thumbnail_path"] = str(output / "thumbnail.jpg")
        existing = metadata.get("youtube_id") or _read(output / "upload_result.json").get("id")
        if existing:
            result = schedule_video(
                cfg, str(existing), slot, video_path=output / "video.mp4", meta=metadata,
            )
            result["url"] = metadata.get("youtube_url") or f"https://youtu.be/{existing}"
        else:
            result = upload_video(
                cfg, output / "video.mp4", metadata,
                privacy_override="private", publish_at=slot,
            )
        if not result.get("thumbnail_set") or not result.get("schedule_confirmed"):
            metadata.update({
                "status": "private_uploaded", "uploaded": True,
                "youtube_id": result["id"], "youtube_url": result["url"],
                "publish_at": None, "audit_id": result.get("audit_id"),
            })
            _write(metadata_path, metadata)
            _write(output / "upload_result.json", result)
            event("compilation_held_private", episode_start=start, episode_end=end)
            return {"episode_range": [start, end], "status": "held_private"}
        metadata.update({
            "status": "scheduled", "uploaded": True,
            "youtube_id": result["id"], "youtube_url": result["url"],
            "publish_at": slot, "audit_id": result.get("audit_id"),
        })
        _write(metadata_path, metadata)
        _write(output / "upload_result.json", result)
        event("compilation_scheduled", episode_start=start, episode_end=end, publish_at=slot)
        return {"episode_range": [start, end], "status": "scheduled", "publish_at": slot}
    return None


def run(args) -> dict[str, Any]:
    cfg = Config(args.config)
    if not cfg.get("autopilot", "enabled", default=False):
        raise RuntimeError("Autopilot is disabled in configuration")
    pause_path = ROOT / str(cfg.get("autopilot", "emergency_pause_file", default="analytics/PAUSE_AUTOPILOT"))
    if pause_path.exists():
        reason = pause_path.read_text(encoding="utf-8", errors="replace")[:500]
        raise RuntimeError(f"Autopilot emergency pause is active: {reason}")
    state = {
        "schema_version": 1,
        "run_id": _now().strftime("run-%Y%m%dT%H%M%SZ"),
        "started_at": _now().isoformat().replace("+00:00", "Z"),
        "status": "running", "normal_manual_actions": 0,
        "fail_closed": True, "stages": {},
    }
    _write(STATE_PATH, state)
    event("run_started", run_id=state["run_id"], dry_run=args.dry_run)
    try:
        release_integrity_ok = False
        youtube_enabled = platform_control.enabled("youtube")
        relaunch_active = bool(cfg.get("meta", "owner_authorized_relaunch", default=False))
        if not args.no_network and not args.dry_run and youtube_enabled:
            try:
                metrics = refresh_metrics(cfg, no_google=args.no_google)
                state["stages"]["metrics_and_learning"] = {"status": "passed", **metrics}
                release_integrity_ok = metrics.get("release_reconciliation") == "passed"
            except Exception as exc:
                state["stages"]["metrics_and_learning"] = {
                    "status": "degraded_local_fallback", "error_type": type(exc).__name__,
                }
                growth_learning.refresh_learning(cfg)
                growth_learning.write_production_directives()
                event("metrics_degraded", error_type=type(exc).__name__)
        else:
            learning = growth_learning.refresh_learning(cfg)
            growth_learning.write_production_directives()
            state["stages"]["metrics_and_learning"] = {
                "status": "youtube_disabled" if not youtube_enabled else "local_only",
                "observations": len(learning["observations"]),
            }

        inventory = studio_inventory.refresh_inventory(cfg)
        factory = story_factory.reconcile(cfg, inventory)
        state["stages"]["evergreen_story_factory"] = {
            "status": "passed", "next_action": factory.get("next_action"),
            "active_task_id": factory.get("active_task_id"),
        }
        state["stages"]["inventory_before"] = {
            "status": "passed", "ready": inventory["ready_or_scheduled_count"],
            "shortage": inventory["shortage"],
        }
        rendered = {"completed": [], "failed": []} if args.dry_run else render_ready(cfg, inventory, args.render_limit)
        state["stages"]["render"] = {
            "status": "passed" if not rendered["failed"] else "recovery_required", **rendered,
        }
        inventory = studio_inventory.refresh_inventory(cfg)
        scheduled = {"completed": [], "failed": [], "deferred": []}
        if not relaunch_active and not args.dry_run and not args.no_network and youtube_enabled and release_integrity_ok:
            scheduled = schedule_ready(cfg, inventory, args.upload_limit)
        state["stages"]["schedule"] = {
            "status": (
                "platform_disabled" if not youtube_enabled
                else "owner_authorized_relaunch" if relaunch_active
                else "passed" if release_integrity_ok and not args.no_network
                else "blocked_remote_integrity" if not args.no_network and not args.dry_run
                else "network_disabled"
            ),
            **scheduled,
        }
        inventory = studio_inventory.refresh_inventory(cfg)
        compilation = None
        if not relaunch_active and not args.dry_run and not args.no_network and youtube_enabled and release_integrity_ok:
            compilation = build_and_schedule_compilation(cfg, inventory)
        state["stages"]["compilation"] = {
            "status": (
                "platform_disabled" if not youtube_enabled
                else "owner_authorized_relaunch" if relaunch_active
                else "passed" if release_integrity_ok and not args.no_network
                else "blocked_remote_integrity" if not args.no_network and not args.dry_run
                else "network_disabled"
            ),
            "result": compilation,
        }
        meta_queue = meta_platform.reconcile_release_queue(cfg)
        state["stages"]["meta_release_queue"] = {
            "status": "passed", **meta_queue,
            "facebook_enabled": platform_control.enabled("facebook"),
            "instagram_enabled": platform_control.enabled("instagram"),
        }
        state["stages"]["inventory_after"] = {
            "status": "passed", "ready": inventory["ready_or_scheduled_count"],
            "shortage": inventory["shortage"],
        }
        cycle_failed = bool(rendered["failed"] or scheduled["failed"])
        compilation_failed = bool(compilation and compilation.get("status") == "held_private")
        deferred_items = scheduled.get("deferred") or []
        if cycle_failed or compilation_failed:
            state["status"] = "recovery_required"
            state["recovery"] = _describe_failures(rendered.get("failed") or [], scheduled.get("failed") or [])
        elif deferred_items:
            state["status"] = "cooldown"
            state["recovery"] = _describe_failures([], [], deferred=deferred_items)
        elif youtube_enabled and not args.no_network and not args.dry_run and not release_integrity_ok:
            state["status"] = "release_integrity_blocked"
            state["recovery"] = "release integrity gate blocked; reconciliation must pass before scheduling resumes"
        else:
            state["status"] = "healthy" if not inventory["shortage"] else "building_buffer"
            state["recovery"] = "none"
    except Exception as exc:
        state["status"] = "failed_closed"
        state["error_type"] = type(exc).__name__
        state["error"] = str(exc)[:500]
        event("run_failed_closed", run_id=state["run_id"], error_type=type(exc).__name__)
        raise
    finally:
        state["finished_at"] = _now().isoformat().replace("+00:00", "Z")
        _write(STATE_PATH, state)
    event("run_finished", run_id=state["run_id"], status=state["status"])
    return state


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config.story.yaml")
    parser.add_argument("--once", action="store_true", help="run one resumable controller cycle")
    parser.add_argument("--dry-run", action="store_true", help="reconcile and learn without rendering or network writes")
    parser.add_argument("--no-network", action="store_true", help="disable YouTube and Google calls")
    parser.add_argument("--no-google", action="store_true", help="skip the Google Sheet mirror")
    parser.add_argument("--render-limit", type=int, default=1)
    parser.add_argument("--upload-limit", type=int, default=4)
    args = parser.parse_args()
    try:
        with RunLock():
            result = run(args)
        if result.get("status") == "recovery_required":
            raise RuntimeError("One or more production stages require bounded retry")
        after = result["stages"].get("inventory_after", {})
        print(
            f"AUTOPILOT {result['status']} | ready={after.get('ready', 0)} "
            f"shortage={after.get('shortage', 0)} | manual_actions=0"
        )
    except Exception as exc:
        print(f"AUTOPILOT FAILED CLOSED: {exc}", file=sys.stderr)
        traceback.print_exc()
        raise SystemExit(1)


if __name__ == "__main__":
    main()
