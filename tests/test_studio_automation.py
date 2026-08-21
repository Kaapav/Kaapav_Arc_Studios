from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
import numpy as np
from PIL import Image
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from build_echo_compilation import build as build_compilation
from src.growth_learning import build_window_snapshots, extract_traits
from src.story_factory import validate_candidate_series
from src.title_policy import title_opening_overlap, validate_episode_title
from src.packaging import build_longform_variants
from src.youtube_analytics import _query_traffic_sources
from src import youtube_playlists
from src.studio_inventory import IST, next_compilation_slot, next_short_slots
from src import studio_inventory
from src import control_backup
from src.video import _safe_still_frame
from src.upload import SCOPES
from authorize_youtube_analytics import ANALYTICS_SCOPE, load_credentials
import studio_dashboard
from studio_autopilot import _render_candidates, _schedule_candidates


class StubConfig:
    values = {
        "autopilot": {
            "short_interval_days": 2,
            "minimum_publish_lead_minutes": 60,
        },
        "growth": {
            "organic_learning_starts_episode": 11,
            "exclude_owner_test_episodes_through": 10,
        },
    }

    def get(self, *keys, default=None):
        value = self.values
        for key in keys:
            if not isinstance(value, dict) or key not in value:
                return default
            value = value[key]
        return value


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


class StudioAutomationTests(unittest.TestCase):
    def test_audience_first_title_policy_accepts_specific_stakes(self):
        failures = validate_episode_title(
            "His Dead Father’s Phone Sent a Warning From Tomorrow | ECHO//30 Ep. 1"
        )
        self.assertEqual(failures, [])

    def test_audience_first_title_policy_blocks_generic_hooks(self):
        failures = validate_episode_title("The Warning | ECHO//30 Ep. 1")
        self.assertTrue(failures)
        self.assertTrue(any("generic" in failure for failure in failures))

    def test_title_opening_must_pay_off_the_promise(self):
        title = "His Dead Father’s Phone Sent a Warning From Tomorrow | ECHO//30 Ep. 1"
        self.assertTrue(title_opening_overlap(title, "His dead father's phone rang at 2:17 AM.")["passed"])
        self.assertFalse(title_opening_overlap(title, "Kavi walked quietly into the arcade.")["passed"])

    def test_longform_packaging_prepares_three_distinct_native_candidates(self):
        payload = build_longform_variants({
            "title": "Five Episodes. One Story. | ECHO//30 Episodes 1–5",
            "series_id": "echo30", "episode_start": 1, "episode_end": 5,
        })
        titles = [item["title"] for item in payload["candidates"]]
        self.assertEqual(len(titles), 3)
        self.assertEqual(len(set(titles)), 3)
        self.assertEqual(payload["selection_metric"], "watch_time")

    def test_youtube_analytics_collects_real_traffic_source_rows(self):
        service = MagicMock()
        service.reports.return_value.query.return_value.execute.return_value = {
            "columnHeaders": [
                {"name": "insightTrafficSourceType"}, {"name": "views"},
                {"name": "engagedViews"}, {"name": "estimatedMinutesWatched"},
            ],
            "rows": [["SHORTS", 12, 9, 4.2], ["YT_SEARCH", 2, 2, 1.0]],
        }
        rows = _query_traffic_sources(service, "video", "2026-08-01", "2026-08-02")
        self.assertEqual(rows[0]["insightTrafficSourceType"], "SHORTS")
        self.assertEqual(rows[0]["engagedViews"], 9)

    def test_playlist_router_is_idempotent_and_persists_identity(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            plan = root / "plan.json"
            state = root / "state.json"
            write_json(plan, {"series": [{
                "slug": "echo30", "public_title": "ECHO//30", "genre": "sci-fi mystery",
            }]})
            service = MagicMock()
            service.playlists.return_value.list.return_value.execute.side_effect = [
                {"items": []}, {"items": [{"id": "playlist-1"}]},
            ]
            service.playlists.return_value.insert.return_value.execute.return_value = {"id": "playlist-1"}
            service.playlistItems.return_value.list.return_value.execute.side_effect = [
                {"items": []}, {"items": [{"id": "item-1"}]},
            ]
            old = youtube_playlists.STATE_PATH, youtube_playlists.PLAN_PATH
            try:
                youtube_playlists.STATE_PATH, youtube_playlists.PLAN_PATH = state, plan
                first = youtube_playlists.route_release(service, {"series_id": "echo30"}, "video-1")
                second = youtube_playlists.route_release(service, {"series_id": "echo30"}, "video-1")
                self.assertEqual((first["status"], second["status"]), ("routed", "routed"))
                self.assertEqual(json.loads(state.read_text(encoding="utf-8"))["series"]["echo30"], "playlist-1")
                self.assertEqual(service.playlistItems.return_value.insert.call_count, 1)
            finally:
                youtube_playlists.STATE_PATH, youtube_playlists.PLAN_PATH = old

    def test_background_launchers_are_permanently_hidden(self):
        root = Path(__file__).resolve().parents[1]
        hidden = (root / "run_hidden.vbs").read_text(encoding="utf-8")
        autopilot_installer = (root / "install_autopilot_scheduler.ps1").read_text(encoding="utf-8")
        dashboard_installer = (root / "install_dashboard_gateway.ps1").read_text(encoding="utf-8")
        self.assertIn('shell.Run(command, 0, True)', hidden)
        self.assertIn('-WindowStyle Hidden', hidden)
        self.assertIn('wscript.exe', autopilot_installer)
        self.assertIn('run_hidden.vbs', autopilot_installer)
        self.assertIn('wscript.exe', dashboard_installer)
        self.assertIn('run_hidden.vbs', dashboard_installer)

    def test_bounded_memory_compositor_returns_exact_uint8_frame(self):
        source = Image.new("RGB", (72, 128), (20, 60, 100))
        vignette = Image.new("RGBA", (72, 128), (0, 0, 0, 24))
        caption = Image.new("RGBA", (72, 128), (0, 0, 0, 0))
        frame = _safe_still_frame(
            source, vignette, caption, 72, 128, 4.0, 2.0, "push_in", 0,
        )
        self.assertEqual(frame.shape, (128, 72, 3))
        self.assertEqual(frame.dtype, np.uint8)
        self.assertEqual(frame.nbytes, 72 * 128 * 3)
        source.close()
        vignette.close()
        caption.close()

    def test_dashboard_has_five_simple_glass_tabs(self):
        html = (Path(__file__).parents[1] / "dashboard" / "index.html").read_text(encoding="utf-8")
        self.assertEqual(html.count('<button class="tab'), 6)
        for name in ("overview", "production", "releases", "performance", "system"):
            self.assertIn(f'data-tab="{name}"', html)
        self.assertIn("backdrop-filter:blur", html)

    def test_web_and_flutter_dashboards_share_platform_control_and_evidence_contract(self):
        root = Path(__file__).parents[1]
        html = (root / "dashboard" / "index.html").read_text(encoding="utf-8")
        flutter = (root / "flutter" / "kaapav_control_room" / "lib" / "main.dart").read_text(encoding="utf-8")
        for route in ("/api/autopilot-control", "/api/platform-control"):
            self.assertIn(route, html)
            self.assertIn(route, flutter)
        for platform in ("youtube", "facebook", "instagram"):
            self.assertIn(platform, html)
            self.assertIn(platform, flutter)
        for evidence in ("meta_queue", "meta_analytics", "platform_learning", "meta_scheduler"):
            self.assertIn(evidence, html)
            self.assertIn(evidence, flutter)
        for label in ("Overview", "Production", "Releases", "Performance", "System"):
            self.assertIn(label, flutter)

    def test_dashboard_reports_pause_and_exact_next_task(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            write_json(root / "analytics" / "studio_inventory.json", {
                "fail_closed": True, "target_ready_shorts": 7, "episodes": [],
            })
            write_json(root / "analytics" / "production_queue.json", {"tasks": [{
                "priority": 1, "action": "render", "series_id": "echo30", "episode": 12,
            }]})
            (root / "analytics" / "PAUSE_AUTOPILOT").write_text("test", encoding="utf-8")
            old_root = studio_dashboard.ROOT
            try:
                studio_dashboard.ROOT = root
                result = studio_dashboard.build_status()
                self.assertEqual(result["studio"]["mode"], "PAUSED")
                self.assertFalse(result["studio"]["working_now"])
                self.assertEqual(result["studio"]["next_task"]["episode"], 12)
            finally:
                studio_dashboard.ROOT = old_root

    def test_dashboard_remote_session_is_signed_and_bootstrap_is_single_use(self):
        with tempfile.TemporaryDirectory() as raw:
            old_secret = studio_dashboard.SECRET_PATH
            try:
                studio_dashboard.SECRET_PATH = Path(raw) / "credentials" / "dashboard.bin"
                code = studio_dashboard.issue_bootstrap_code()
                self.assertTrue(studio_dashboard.consume_bootstrap_code(code))
                self.assertFalse(studio_dashboard.consume_bootstrap_code(code))
                session = studio_dashboard.issue_session()
                self.assertTrue(studio_dashboard.valid_session(session))
                self.assertFalse(studio_dashboard.valid_session(session + "tampered"))
            finally:
                studio_dashboard.SECRET_PATH = old_secret

    def test_dashboard_owner_control_changes_real_pause_gate(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            analytics = root / "analytics"
            analytics.mkdir()
            (analytics / "setup_certification.json").write_text(
                json.dumps({"status": "certified_paused", "failed_checks": []}),
                encoding="utf-8",
            )
            old_root = studio_dashboard.ROOT
            try:
                studio_dashboard.ROOT = root
                with patch.object(
                    studio_dashboard, "scheduler_action",
                    return_value={"ok": True, "action": "changed", "exit_code": 0, "error": None},
                ):
                    disabled = studio_dashboard.set_automation_enabled(False, "test")
                    self.assertTrue(disabled["ok"])
                    self.assertTrue((analytics / "PAUSE_AUTOPILOT").exists())
                    enabled = studio_dashboard.set_automation_enabled(True, "test")
                    self.assertTrue(enabled["ok"])
                    self.assertFalse((analytics / "PAUSE_AUTOPILOT").exists())
                (analytics / "PAUSE_AUTOPILOT").write_text("paused\n", encoding="utf-8")
                with patch.object(
                    studio_dashboard, "scheduler_action",
                    return_value={"ok": False, "action": "started", "exit_code": 1, "error": "test failure"},
                ):
                    failed = studio_dashboard.set_automation_enabled(True, "test")
                    self.assertFalse(failed["ok"])
                    self.assertFalse(failed["enabled"])
                    self.assertEqual(failed["production_gate"], "closed")
                    self.assertTrue((analytics / "PAUSE_AUTOPILOT").exists())
            finally:
                studio_dashboard.ROOT = old_root

    def test_analytics_upgrade_detects_legacy_scope(self):
        self.assertIn(ANALYTICS_SCOPE, SCOPES)
        with tempfile.TemporaryDirectory() as raw:
            token = Path(raw) / "token.json"
            from google.oauth2.credentials import Credentials
            credentials = Credentials(
                token="test", refresh_token="refresh", token_uri="https://oauth2.googleapis.com/token",
                client_id="client", client_secret="secret",
                scopes=["https://www.googleapis.com/auth/youtube.upload"],
            )
            token.write_text(credentials.to_json(), encoding="utf-8")
            loaded = load_credentials(token)
            self.assertFalse(loaded.has_scopes([ANALYTICS_SCOPE]))

    def test_inventory_resolves_zero_padded_episode_folders(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            manifest = root / "episode01" / "episode.json"
            write_json(manifest, {"episode": 1})
            self.assertEqual(studio_inventory._manifest_path(root, 1), manifest)

    def test_remote_release_index_recognizes_legacy_echo_titles(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            analytics = root / "analytics"
            analytics.mkdir()
            (analytics / "current.csv").write_text(
                "video_id,title,privacy,published_at,remote_publish_at,url,series_id,episode\n"
                "abc,The Phone Warned Him | ECHO//30 Ep. 1,public,2026-08-09T03:30:00Z,,https://youtu.be/abc,,\n",
                encoding="utf-8-sig",
            )
            old_root = studio_inventory.ROOT
            try:
                studio_inventory.ROOT = root
                index = studio_inventory._remote_release_index()
                self.assertEqual(index[("echo30", 1)]["state"], "public")
            finally:
                studio_inventory.ROOT = old_root

    def test_control_backup_excludes_credentials_and_media(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            write_json(root / "content" / "series.json", {"title": "SAFE"})
            (root / "studio_autopilot.py").write_text("print('safe')", encoding="utf-8")
            (root / "credentials").mkdir()
            (root / "credentials" / "token.json").write_text("SECRET", encoding="utf-8")
            (root / "output").mkdir()
            (root / "output" / "video.mp4").write_bytes(b"MEDIA")
            old = (control_backup.ROOT, control_backup.BACKUP_ROOT, control_backup.STATE_PATH)
            try:
                control_backup.ROOT = root
                control_backup.BACKUP_ROOT = root / "backups" / "control-plane"
                control_backup.STATE_PATH = root / "analytics" / "backup_state.json"
                result = control_backup.create_daily_snapshot(7)
                with zipfile.ZipFile(result["path"], "r") as archive:
                    names = set(archive.namelist())
                self.assertIn("content/series.json", names)
                self.assertIn("studio_autopilot.py", names)
                self.assertNotIn("credentials/token.json", names)
                self.assertNotIn("output/video.mp4", names)
                self.assertNotIn("analytics/backup_state.json", names)
                second = control_backup.create_daily_snapshot(7)
                self.assertEqual(second["source_fingerprint"], result["source_fingerprint"])
                self.assertEqual(second["sha256"], result["sha256"])
            finally:
                control_backup.ROOT, control_backup.BACKUP_ROOT, control_backup.STATE_PATH = old

    def test_short_slots_keep_two_day_cadence_at_ten_ist(self):
        slots = next_short_slots(["2026-08-18T03:30:00Z"], 3, StubConfig())
        local = [datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(IST) for value in slots]
        self.assertEqual(len(local), 3)
        now = datetime.now(IST)
        for index, value in enumerate(local):
            self.assertEqual((value.hour, value.minute), (10, 0))
            self.assertGreater(value, now)
            if index:
                self.assertEqual((value - local[index - 1]).days, 2)

    def test_scheduler_never_jumps_an_unresolved_episode(self):
        inventory = {
            "active_series_sequence": 1,
            "episodes": [
                {"sequence": 1, "episode": 11, "state": "scheduled"},
                {"sequence": 1, "episode": 12, "state": "images_pending"},
                {"sequence": 1, "episode": 13, "state": "strict_audit_passed"},
            ],
        }
        self.assertEqual(_schedule_candidates(StubConfig(), inventory, 4), [])
        inventory["episodes"][1]["state"] = "strict_audit_passed"
        self.assertEqual(
            [item["episode"] for item in _schedule_candidates(StubConfig(), inventory, 4)],
            [12, 13],
        )

    def test_renderer_respects_buffer_cap_and_episode_gaps(self):
        inventory = {
            "active_series_sequence": 1, "shortage": 1, "target_ready_shorts": 7,
            "episodes": [
                {"sequence": 1, "episode": 11, "state": "scheduled"},
                {"sequence": 1, "episode": 12, "state": "images_pending"},
                {"sequence": 1, "episode": 13, "state": "render_ready"},
            ],
        }
        self.assertEqual(_render_candidates(StubConfig(), inventory, 1), [])
        inventory["episodes"][1]["state"] = "render_ready"
        self.assertEqual(_render_candidates(StubConfig(), inventory, 1)[0]["episode"], 12)
        inventory["shortage"] = 0
        self.assertEqual(_render_candidates(StubConfig(), inventory, 1), [])

    def test_compilation_uses_next_weekend_at_ten_ist(self):
        slot = next_compilation_slot("2026-08-20T03:30:00Z", StubConfig())
        local = datetime.fromisoformat(slot.replace("Z", "+00:00")).astimezone(IST)
        self.assertIn(local.weekday(), {5, 6})
        self.assertEqual((local.hour, local.minute), (10, 0))

    def test_compilation_rejects_any_non_five_episode_block(self):
        with self.assertRaisesRegex(ValueError, "exactly five"):
            build_compilation(11, 16)

    def test_trait_extraction_is_deterministic(self):
        manifest = {
            "title": "His Future Voice Warned Him",
            "thumbnail_text": "9 MINUTES LEFT",
            "permanent_story_change": "She chooses to trust her former rival.",
            "scenes": [{"text": "Only nine minutes remained."}],
        }
        traits = extract_traits(manifest)
        self.assertEqual(traits["title_framing"], "urgent_warning")
        self.assertEqual(traits["opening_hook"], "countdown")
        self.assertEqual(traits["thumbnail_focus"], "countdown_symbol")
        self.assertEqual(traits["story_engine"], "relationship_choice")

    def test_learning_keeps_window_history_and_does_not_exclude_future_series_episode_one(self):
        base = {
            "video_id": "future-1", "series_id": "static9", "episode": "1",
            "title": "A New Signal | STATIC//9 Ep. 1", "privacy": "public",
            "published_at": "2026-08-01T00:00:00+00:00",
            "snapshot_at": "2026-08-02T01:00:00+00:00",
            "views": "25", "likes": "3", "comments": "1",
        }
        owner_test = {
            **base, "video_id": "owner-1", "series_id": "echo30",
            "title": "The Phone Warned Him | ECHO//30 Ep. 1",
        }
        snapshots = build_window_snapshots(StubConfig(), [base, owner_test])
        self.assertEqual(len(snapshots), 1)
        self.assertEqual((snapshots[0]["series_id"], snapshots[0]["window_hours"]), ("static9", 24))

    def test_story_factory_accepts_a_complete_causal_blueprint(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "SERIES_BIBLE.md").write_text("Original world and character rules. " * 80, encoding="utf-8")
            write_json(root / "series.json", {"title": "THE LAST RAIN SIGNAL"})
            for episode in range(1, 31):
                write_json(root / "episodes" / f"ep{episode:03d}" / "episode.json", {
                    "episode": episode,
                    "title": f"The Signal Changed Person {episode}",
                    "description": f"A distinct consequence unfolds in chapter {episode}.",
                    "permanent_story_change": f"Relationship state {episode} changes permanently after a causal choice.",
                    "scenes": [
                        {
                            "text": f"The Signal Changed Person {episode} opens with a distinct scene {scene}.",
                            "image_prompt": f"Distinct visual intention {episode}-{scene} with causal action.",
                        }
                        for scene in range(1, 7)
                    ],
                })
            report = validate_candidate_series(root, existing_titles=["ECHO//30"])
            self.assertEqual(report["status"], "passed", report["failures"])
            self.assertEqual(report["episode_count"], 30)


if __name__ == "__main__":
    unittest.main()
