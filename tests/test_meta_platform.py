from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from src import meta_platform, platform_control, story_factory
from src.release_audit import PublishAuditError, assert_persisted_release_evidence, _metadata_sha256


class StubConfig:
    values = {
        "meta": {"public_media_base_url": "https://yt.kaapav.com"},
        "autopilot": {
            "initial_series_count": 10,
            "evergreen_story_factory": True,
            "evergreen_refill_remaining_series": 2,
            "evergreen_series_batch_size": 10,
            "policy_applies_from_episode": 11,
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


class MetaPlatformTests(unittest.TestCase):
    def test_platform_controls_are_independent_and_persistent(self):
        with tempfile.TemporaryDirectory() as raw:
            old = platform_control.STATE_PATH
            try:
                platform_control.STATE_PATH = Path(raw) / "controls.json"
                self.assertTrue(platform_control.enabled("youtube"))
                self.assertFalse(platform_control.enabled("facebook"))
                platform_control.set_enabled("facebook", True, source="test")
                self.assertTrue(platform_control.enabled("facebook"))
                self.assertFalse(platform_control.enabled("instagram"))
            finally:
                platform_control.STATE_PATH = old

    def test_meta_caption_is_platform_specific_and_removes_youtube_links(self):
        caption = meta_platform.build_caption({
            "title": "The Door Remembered Her | ECHO//30 Ep. 11",
            "description": "A real causal story change.\nSubscribe now.\nhttps://youtube.com/example",
            "tags": ["sci fi", "KAAPAV ARC Studios", "time-loop"],
        }, "instagram")
        self.assertIn("Follow KAAPAV ARC Studios", caption)
        self.assertIn("#scifi", caption)
        self.assertNotIn("youtube.com", caption)
        self.assertNotIn("Subscribe now", caption)

    def test_facebook_can_be_ready_while_null_instagram_link_stays_blocked(self):
        account = {
            "page_id": "123", "page_name": "KAAPAV ARC Studios",
            "page_tasks": ["CREATE_CONTENT", "MANAGE"], "page_token": "unused",
            "instagram_id": "", "instagram_username": "", "instagram_name": "",
        }
        with patch.object(meta_platform, "credential_present", return_value=True), patch.object(
            meta_platform.MetaClient, "discover", return_value=account,
        ):
            status = meta_platform.health_check(StubConfig(), write=False)
        self.assertEqual(status["status"], "partial")
        self.assertEqual(status["platforms"]["facebook"]["status"], "ready")
        self.assertEqual(status["platforms"]["instagram"]["status"], "not_linked")

    def test_signed_media_grant_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            video = root / "output" / "story" / "ep11" / "video.mp4"
            video.parent.mkdir(parents=True)
            video.write_bytes(b"safe-video-bytes")
            old = (
                meta_platform.ROOT, meta_platform.MEDIA_GRANTS_PATH,
                meta_platform.MEDIA_SECRET_PATH,
            )
            try:
                meta_platform.ROOT = root
                meta_platform.MEDIA_GRANTS_PATH = root / "analytics" / "grants.json"
                meta_platform.MEDIA_SECRET_PATH = root / "credentials" / "media.bin"
                url = meta_platform.issue_media_grant(StubConfig(), video, audit_id="audit-1")
                route = url.removeprefix("https://yt.kaapav.com")
                self.assertEqual(meta_platform.resolve_media_grant(route), video.resolve())
                self.assertIsNone(meta_platform.resolve_media_grant(route.replace("/video.mp4", "/other.mp4")))
            finally:
                meta_platform.ROOT, meta_platform.MEDIA_GRANTS_PATH, meta_platform.MEDIA_SECRET_PATH = old

    def test_release_queue_adds_future_platform_items_but_never_backfills_past(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            video = root / "episode11" / "video.mp4"
            video.parent.mkdir(parents=True)
            video.write_bytes(b"video")
            write_json(video.parent / "metadata.json", {"title": "Future episode"})
            write_json(video.parent / "prepublish_audit.json", {"status": "passed"})
            future = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat().replace("+00:00", "Z")
            past = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat().replace("+00:00", "Z")
            entries = [
                {"series_id": "echo30", "episode_id": "echo30-ep011", "episode": 11,
                 "release_kind": "short", "video_path": str(video), "video_sha256": meta_platform._sha256(video),
                 "audit_id": "audit-11", "publish_at": future, "title": "Future"},
                {"series_id": "echo30", "episode_id": "echo30-ep010", "episode": 10,
                 "release_kind": "short", "video_path": str(video), "video_sha256": meta_platform._sha256(video),
                 "audit_id": "audit-10", "publish_at": past, "title": "Past"},
            ]
            old = (meta_platform.QUEUE_PATH, meta_platform.LEDGER_PATH)
            try:
                meta_platform.QUEUE_PATH = root / "queue.json"
                meta_platform.LEDGER_PATH = root / "ledger.json"
                with patch("src.release_ledger.sync_from_outputs", return_value={"releases": entries}):
                    result = meta_platform.reconcile_release_queue(StubConfig())
                self.assertEqual(result["added"], 2)
                queued = json.loads(meta_platform.QUEUE_PATH.read_text())["items"]
                self.assertEqual({item["platform"] for item in queued}, {"facebook", "instagram"})
                self.assertTrue(all(item["episode"] == 11 for item in queued))
            finally:
                meta_platform.QUEUE_PATH, meta_platform.LEDGER_PATH = old

    def test_persisted_audit_rehashes_inputs_without_age_exception(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            video = root / "video.mp4"
            thumbnail = root / "thumbnail.jpg"
            script = root / "script.json"
            video.write_bytes(b"video")
            thumbnail.write_bytes(b"thumb")
            script.write_text("{}", encoding="utf-8")
            meta = {
                "title": "A sufficiently long episode title", "description": "story", "tags": ["a"],
                "series_id": "echo30", "episode_id": "echo30-ep011", "episode": 11,
                "release_kind": "short", "thumbnail_path": str(thumbnail),
            }
            audit = {
                "audit_id": "audit-old", "created_at": "2020-01-01T00:00:00Z",
                "status": "passed", "fail_closed": True, "failures": [],
                "inputs": {
                    "video": {"path": str(video), "sha256": meta_platform._sha256(video)},
                    "thumbnail": {"path": str(thumbnail), "sha256": meta_platform._sha256(thumbnail)},
                    "script": {"path": str(script), "sha256": meta_platform._sha256(script)},
                    "metadata": {"sha256": _metadata_sha256(meta)},
                },
            }
            audit_path = root / "prepublish_audit.json"
            write_json(audit_path, audit)
            self.assertEqual(assert_persisted_release_evidence(video, meta, audit_path)["audit_id"], "audit-old")
            video.write_bytes(b"changed")
            with self.assertRaises(PublishAuditError):
                assert_persisted_release_evidence(video, meta, audit_path)

    def test_evergreen_factory_refills_ten_when_only_two_series_remain(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            plan = root / "plan.json"
            queue = root / "queue.json"
            state = root / "state.json"
            write_json(plan, {"series": [{"sequence": value} for value in range(1, 11)]})
            inventory = {"episodes": [
                {"sequence": sequence, "state": "public" if sequence <= 8 else "images_pending"}
                for sequence in range(1, 11) for _ in range(30)
            ]}
            old = (story_factory.PLAN_PATH, story_factory.QUEUE_PATH, story_factory.STATE_PATH)
            try:
                story_factory.PLAN_PATH, story_factory.QUEUE_PATH, story_factory.STATE_PATH = plan, queue, state
                first = story_factory.reconcile(StubConfig(), inventory)
                self.assertEqual(first["next_action"], "successor_batch_queued")
                self.assertEqual(len(first["created_task_ids"]), 10)
                second = story_factory.reconcile(StubConfig(), inventory)
                self.assertEqual(second["created_task_ids"], [])
                self.assertEqual(len(json.loads(queue.read_text())["tasks"]), 10)
            finally:
                story_factory.PLAN_PATH, story_factory.QUEUE_PATH, story_factory.STATE_PATH = old


if __name__ == "__main__":
    unittest.main()
