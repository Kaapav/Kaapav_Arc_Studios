from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image, ImageDraw

from src.release_audit import PublishAuditError, assert_fresh_audit, run_publish_audit
from src.provenance import write_rights_manifest
from src import release_ledger

IST = timezone(timedelta(hours=5, minutes=30), name="IST")


class StubConfig:
    data = {
        "youtube": {"expected_channel_id": "UCylPn80btY6lpivJ_N-cXGQ"},
        "autopilot": {"minimum_publish_lead_minutes": 60, "audit_max_age_minutes": 30},
    }

    def get(self, *keys, default=None):
        value = self.data
        for key in keys:
            if not isinstance(value, dict) or key not in value:
                return default
            value = value[key]
        return value


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def make_image(path: Path, size: tuple[int, int], seed: int) -> None:
    image = Image.new("RGB", size, (10 + seed * 5, 25, 60))
    draw = ImageDraw.Draw(image)
    for offset in range(0, max(size), 24):
        draw.line((0, offset, size[0], max(0, offset - size[0])), fill=(200, 30 + seed, 90), width=9)
    draw.ellipse((seed * 7, 40, min(size[0] - 5, seed * 7 + 180), 220), fill=(20, 180, 220))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, quality=92)


class StrictReleaseAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.package = root / "output" / "episode11"
        self.episode_root = root / "style" / "episode11"
        self.frames = self.episode_root / "story_frames"
        self.package.mkdir(parents=True)
        self.frames.mkdir(parents=True)
        scenes = []
        script_scenes = []
        accepted = []
        for index in range(1, 6):
            rel = f"story_frames/shot_{index:02d}.png"
            path = self.episode_root / rel
            make_image(path, (720, 1280), index)
            scenes.append({
                "image": rel,
                "image_prompt": f"Distinct causal action number {index} changes the relationship.",
                "text": f"A meaningful consequence happens in scene {index}.",
            })
            script_scenes.append({
                "image_path": str(path),
                "text": (
                    "The city lost another minute before anyone could breathe."
                    if index == 1 else f"A meaningful consequence happens in scene {index}."
                ),
                "caption": (
                    "The city lost another minute."
                    if index == 1 else f"A meaningful consequence happens in scene {index}."
                ),
            })
            accepted.append(rel)
        write_json(self.episode_root / "episode.json", {
            "series_id": "echo30", "episode": 11,
            "permanent_story_change": "The lead publicly trusts the former rival.",
            "scenes": scenes,
        })
        write_json(self.episode_root / "image_qc.json", {
            "status": "accepted", "accepted_frames": accepted,
        })
        characters = self.episode_root.parent / "characters"
        make_image(characters / "lead_turnaround.png", (1280, 720), 8)
        write_json(characters / "character_registry.json", {
            "locked": [{"character": "Lead", "reference": "lead_turnaround.png", "status": "locked"}],
            "pending_before_first_appearance": [],
        })
        title = "The City Lost Another Minute | ECHO//30 Ep. 11"
        script = {
            "title": title, "series_id": "echo30", "episode_id": "echo30-ep011",
            "scenes": script_scenes,
        }
        write_json(self.package / "script.json", script)
        write_rights_manifest(self.package, script, StubConfig())
        make_image(self.package / "thumbnail.jpg", (1280, 720), 9)
        make_image(self.package / "qc_contact.jpg", (1280, 720), 10)
        self.video = self.package / "video.mp4"
        subprocess.run([
            "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
            "testsrc2=size=360x640:rate=24:duration=21", "-f", "lavfi", "-i",
            "sine=frequency=440:sample_rate=44100:duration=21", "-c:v", "libx264",
            "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(self.video),
        ], check=True)
        write_json(self.package / "qc_report.json", {
            "ok": True, "full_decode": "passed", "contact_sheet": str(self.package / "qc_contact.jpg"),
        })
        self.meta = {
            "title": title,
            "description": (
                "A trapped city loses another minute after its heroes reveal the truth. "
                "The decision permanently changes their alliance and opens a dangerous route. "
                "An original animated mystery from KAAPAV ARC Studios. #ECHO30 #AnimatedSeries"
            ),
            "tags": ["ECHO30", "animated series", "science fiction", "mystery", "KAAPAV ARC Studios"],
            "thumbnail_path": str(self.package / "thumbnail.jpg"),
            "release_kind": "short",
        }

    def tearDown(self):
        self.temp.cleanup()

    def next_slot(self) -> str:
        local = datetime.now(IST) + timedelta(days=2)
        local = local.replace(hour=10, minute=0, second=0, microsecond=0)
        return local.isoformat()

    def test_clean_package_passes_and_hashes_are_locked(self):
        cfg = StubConfig()
        report = run_publish_audit(
            cfg, self.video, self.meta, publish_at=self.next_slot(),
            online_channel={"id": "UCylPn80btY6lpivJ_N-cXGQ", "title": "KAAPAV ARC Studios"},
        )
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["evidence"]["media"]["full_decode"], "passed")
        assert_fresh_audit(cfg, self.video, self.meta, report)

    def test_metadata_mutation_after_audit_is_blocked(self):
        cfg = StubConfig()
        report = run_publish_audit(cfg, self.video, self.meta)
        changed = {**self.meta, "title": "A Different Untested Title | ECHO//30 Ep. 11"}
        with self.assertRaisesRegex(PublishAuditError, "metadata changed"):
            assert_fresh_audit(cfg, self.video, changed, report)

    def test_generic_title_is_blocked_before_release(self):
        weak = {**self.meta, "title": "The Warning | ECHO//30 Ep. 11"}
        script_path = self.package / "script.json"
        script = json.loads(script_path.read_text(encoding="utf-8"))
        script["title"] = weak["title"]
        write_json(script_path, script)
        write_rights_manifest(self.package, script, StubConfig())
        with self.assertRaisesRegex(PublishAuditError, "title policy"):
            run_publish_audit(StubConfig(), self.video, weak)

    def test_missing_visual_acceptance_blocks_release(self):
        (self.episode_root / "image_qc.json").unlink()
        with self.assertRaisesRegex(PublishAuditError, "Visual QC acceptance record is missing"):
            run_publish_audit(StubConfig(), self.video, self.meta)

    def test_wrong_channel_blocks_release(self):
        with self.assertRaisesRegex(PublishAuditError, "Authenticated YouTube channel"):
            run_publish_audit(
                StubConfig(), self.video, self.meta,
                online_channel={"id": "WRONG", "title": "Wrong Channel"},
            )

    def test_missing_rights_manifest_blocks_release(self):
        (self.package / "rights_manifest.json").unlink()
        with self.assertRaisesRegex(PublishAuditError, "rights and provenance"):
            run_publish_audit(StubConfig(), self.video, self.meta)

    def test_release_ledger_blocks_identical_video_reupload(self):
        old_path = release_ledger.LEDGER_PATH
        try:
            release_ledger.LEDGER_PATH = Path(self.temp.name) / "release_ledger.json"
            release_ledger.record(
                self.video,
                {**self.meta, "episode_id": "echo30-ep011", "series_id": "echo30"},
                {"id": "already-uploaded", "status": "scheduled", "thumbnail_set": True},
            )
            with self.assertRaisesRegex(RuntimeError, "Duplicate upload blocked"):
                release_ledger.assert_not_uploaded(
                    self.video, {**self.meta, "episode_id": "echo30-ep011"}
                )
        finally:
            release_ledger.LEDGER_PATH = old_path

    def test_immediate_schedule_blocks_release(self):
        soon = (datetime.now(IST) + timedelta(minutes=5)).isoformat()
        with self.assertRaisesRegex(PublishAuditError, "lead time"):
            run_publish_audit(StubConfig(), self.video, self.meta, publish_at=soon)

    def test_remote_publication_promotes_local_inventory_state(self):
        old_ledger = release_ledger.LEDGER_PATH
        old_reconciliation = release_ledger.RECONCILIATION_PATH
        old_root = release_ledger.ROOT
        try:
            release_ledger.ROOT = Path(self.temp.name)
            release_ledger.LEDGER_PATH = Path(self.temp.name) / "release_ledger.json"
            release_ledger.RECONCILIATION_PATH = Path(self.temp.name) / "reconciliation.json"
            local_meta = {
                **self.meta, "series_id": "echo30", "episode_id": "echo30-ep011",
                "episode": 11, "status": "scheduled", "uploaded": True,
            }
            write_json(self.package / "metadata.json", local_meta)
            publish_at = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
            contract = {
                "snippet": {
                    "title": self.meta["title"], "description": self.meta["description"],
                    "tags": self.meta["tags"], "categoryId": "24", "defaultLanguage": "en",
                }
            }
            release_ledger.record(self.video, local_meta, {
                "id": "scheduled-id", "url": "https://youtu.be/scheduled-id",
                "status": "scheduled", "privacy": "private", "publish_at": publish_at,
                "thumbnail_set": True, "audit_id": "strict-audit", "remote_contract": contract,
            })
            rows = release_ledger.enrich_rows([{
                "video_id": "scheduled-id", "title": self.meta["title"],
                "privacy": "public", "published_at": publish_at, "remote_publish_at": "",
                "made_for_kids": False, "url": "https://youtu.be/scheduled-id",
                "_remote_description": self.meta["description"],
                "_remote_tags": self.meta["tags"], "_remote_category_id": "24",
                "_remote_default_language": "en",
            }])
            self.assertEqual(rows[0]["series_id"], "echo30")
            report = release_ledger.reconcile_remote(rows)
            self.assertEqual(report["status"], "passed", report.get("failures"))
            promoted = json.loads((self.package / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(promoted["status"], "public")
        finally:
            release_ledger.LEDGER_PATH = old_ledger
            release_ledger.RECONCILIATION_PATH = old_reconciliation
            release_ledger.ROOT = old_root


if __name__ == "__main__":
    unittest.main()
