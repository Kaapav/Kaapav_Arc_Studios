#!/usr/bin/env python3
"""Review & publish the day's AI Creative Explorer videos.

Each morning the pipeline uploads a PRIVATE draft and queues it here. You review, then:

    python review.py list                 # see pending drafts + safety status
    python review.py approve <id>         # publish one (private -> public)
    python review.py approve <id> --force # publish one the safety gate HELD
    python review.py reject  <id>         # decline (stays private)
    python review.py approve-safe         # one command: publish ALL safe pending drafts

Before publishing, remember to toggle "Altered or synthetic content" in YouTube Studio
(this is AI-generated) — it's required and has zero downside. See SAFETY.md.
"""
import sys
from src.config import Config
from src import review

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def _fmt(it):
    s = it["safety"]
    if it["status"] == "held":
        flags = ", ".join(f["category"] for f in s.get("flags", [])) or "profanity"
        badge = f"⛔ HELD ({flags})"
    elif s.get("profanity"):
        badge = f"⚠ profanity: {', '.join(s['profanity'])}"
    else:
        badge = "✅ safe"
    return (f"  {it['id']}  [{it['status']}]  {badge}\n"
            f"      {it['title']}\n"
            f"      draft: {it.get('youtube_url') or it['video_path']}")


def main(argv):
    cfg = Config()
    cmd = argv[0] if argv else "list"

    if cmd == "list":
        items = review.pending(cfg)
        if not items:
            print("Nothing pending. All caught up. ✨")
            return
        print(f"{len(items)} draft(s) awaiting review:\n")
        for it in items:
            print(_fmt(it))
            print()
        print("Approve with:  python review.py approve <id>   (or)   approve-safe")
        return

    if cmd == "approve-safe":
        print(review.approve_all_safe(cfg))
        return

    if cmd in ("approve", "reject"):
        if len(argv) < 2:
            print(f"Usage: python review.py {cmd} <id>")
            return
        item_id = argv[1]
        if cmd == "approve":
            force = "--force" in argv[2:]
            print(review.approve(cfg, item_id, force=force))
        else:
            print(review.reject(cfg, item_id))
        return

    print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
