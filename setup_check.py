#!/usr/bin/env python3
"""Setup doctor — run `python setup_check.py` any time to see EXACTLY what's left.

Checks your machine and keys one by one, live-tests the keys it finds, and prints
your setup % with the single next action. No guesswork, no README hunting.
"""
import importlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def ok(msg):    print(f"  [OK]   {msg}")
def todo(msg):  print(f"  [TODO] {msg}")
def warn(msg):  print(f"  [WARN] {msg}")


def check_python():
    v = sys.version_info
    if v >= (3, 10):
        ok(f"Python {v.major}.{v.minor}")
        return True
    todo(f"Python {v.major}.{v.minor} — need 3.10+. Install from python.org (tick 'Add to PATH').")
    return False


def check_ffmpeg():
    if shutil.which("ffmpeg"):
        ok("ffmpeg found")
        return True
    todo("ffmpeg missing — PowerShell:  winget install ffmpeg   (then reopen terminal)")
    return False


def check_packages():
    missing = []
    for mod, pipname in [("yaml", "pyyaml"), ("dotenv", "python-dotenv"),
                         ("edge_tts", "edge-tts"), ("moviepy", "moviepy"),
                         ("PIL", "Pillow"), ("numpy", "numpy"),
                         ("imageio_ffmpeg", "imageio-ffmpeg"),
                         ("requests", "requests"), ("openai", "openai"),
                         ("googleapiclient", "google-api-python-client"),
                         ("piper", "piper-tts"), ("faster_whisper", "faster-whisper")]:
        try:
            importlib.import_module(mod)
        except ImportError:
            missing.append(pipname)
    if not missing:
        ok("all Python packages installed")
        return True
    todo(f"missing: {', '.join(missing)}  — run:  pip install -r requirements.txt")
    return False


def check_env_file():
    if (ROOT / ".env").exists():
        ok(".env file exists")
        return True
    todo("no .env file — copy .env.example to .env, then add your keys")
    return False


def check_llm():
    try:
        from src.config import Config
        cfg = Config()
    except Exception as e:
        todo(f"config problem: {e}")
        return False
    if not cfg.has_llm:
        todo("no LLM key — FREE: create a Gemini API key at https://aistudio.google.com/apikey "
             "and paste it in .env as GEMINI_API_KEY")
        return False
    try:
        import src.llm as llm
        reply = llm.chat(cfg, "Reply with exactly: READY", temperature=0, max_tokens=5)
        used_provider = llm.last_provider or cfg.active_llm_provider
        profile = cfg.llm_profiles().get(used_provider, {})
        used_model = llm.last_model or profile.get("model", "?")
        ok(f"LLM key works ({used_provider}/{used_model}) -> '{reply[:20]}'")
        chain = " -> ".join(cfg.llm_candidates())
        print(f"         Fallback chain: {chain or 'template-only'}")
        if cfg.groq_key and cfg.groq_model == "llama-3.3-70b-versatile":
            warn("Groq llama-3.3-70b-versatile retires 2026-08-16; runtime replacement is enabled")
        return True
    except Exception as e:
        todo(f"LLM key set but call failed: {str(e)[:110]}")
        if "models.github.ai" in cfg.openai_base:
            print("         GitHub Models was retired on 2026-07-30. Use Gemini instead:")
            print("         GEMINI_API_KEY=...   GEMINI_MODEL=gemini-flash-lite-latest")
        return False


def check_pexels():
    try:
        from src.config import Config
        cfg = Config()
    except Exception:
        return False
    if not cfg.pexels_key:
        warn("no Pexels key (videos fall back to gradient backgrounds). Free: pexels.com/api")
        return False
    try:
        import requests
        r = requests.get("https://api.pexels.com/v1/search?query=ai&per_page=1",
                         headers={"Authorization": cfg.pexels_key}, timeout=15)
        if r.status_code == 200:
            ok("Pexels key works")
            return True
        todo(f"Pexels key rejected (HTTP {r.status_code}) — re-copy from pexels.com/api")
    except Exception as e:
        warn(f"Pexels check skipped (network?): {e.__class__.__name__}")
    return False


def check_offline_voice():
    """Confirm that narration still works when every hosted voice is down."""
    try:
        from src.config import Config
        cfg = Config()
        model = Path(cfg.get(
            "voice", "piper_model", default="assets/voices/piper/en_US-lessac-medium.onnx"
        ))
        if not model.is_absolute():
            model = ROOT / model
        piper_ready = model.exists() and model.with_suffix(model.suffix + ".json").exists()
        sapi_ready = os.name == "nt" and shutil.which("powershell") is not None
        if piper_ready:
            ok("offline Piper voice model ready (no API, no GPU)")
            return True
        if sapi_ready:
            ok("Windows offline voice fallback ready")
            return True
        todo("no offline voice fallback; restore the Piper model under assets/voices/piper")
    except Exception as exc:
        todo(f"offline voice check failed: {exc}")
    return False


def _youtube_token_valid(token: Path) -> bool:
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from src.upload import SCOPES

        creds = Credentials.from_authorized_user_file(str(token), SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            token.write_text(creds.to_json(), encoding="utf-8")
        if creds.valid:
            return True
        todo("YouTube token exists but is invalid; run python authorize_youtube.py")
    except Exception as exc:
        todo(f"YouTube token cannot refresh ({str(exc)[:100]}); re-authorize once")
    return False


def check_youtube():
    try:
        from src.config import Config
        from src.upload import resolve_client_secret
        cfg = Config()
        secret = resolve_client_secret(cfg)
        token = ROOT / cfg.yt_token
    except Exception:
        secret = ROOT / "credentials" / "client_secret.json"
        token = ROOT / "credentials" / "token.json"
    if not secret.exists():
        todo("no credentials/client_secret.json — README section C (Google Cloud OAuth, ~15 min)")
        return False
    ok("OAuth client file found")
    if token.exists() and _youtube_token_valid(token):
        try:
            from src.upload import verify_upload_target
            target = verify_upload_target(cfg)
            ok(f"YouTube authorized — correct upload target: {target['title']}")
            return True
        except Exception as exc:
            todo(str(exc))
            return False
    todo("not authorized yet — run `python authorize_youtube.py --switch-channel` and choose AI Creative Explorer")
    return False


def check_scheduler():
    """A workflow file alone is not automation; verify an active trigger exists."""
    if os.name == "nt":
        command = (
            "Get-ScheduledTask -ErrorAction SilentlyContinue | "
            "Where-Object { $_.TaskName -match 'YT-Auto|AI Creative|YouTube' } | "
            "Select-Object -ExpandProperty TaskName"
        )
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                capture_output=True, text=True, timeout=15,
            )
            names = {line.strip() for line in result.stdout.splitlines() if line.strip()}
            required = {"YT-Auto Daily Draft", "YT-Auto Performance Sync"}
            if required.issubset(names):
                ok("daily draft and performance schedules found (09:00 / 21:00)")
                return True
            if names:
                todo(f"scheduler incomplete; found: {', '.join(sorted(names))}")
                return False
        except Exception:
            pass
    if (ROOT / ".git").exists() and (ROOT / ".github" / "workflows" / "daily.yml").exists():
        ok("GitHub workflow is in an initialized repository")
        return True
    todo("no active daily trigger; the workflow file is dormant because this folder is not a Git repository")
    return False


def check_performance_tracker():
    """Confirm local-first analytics exists and Google mirror is coherent if enabled."""
    tracker = ROOT / "performance_tracker.py"
    current = ROOT / "analytics" / "current.csv"
    if not tracker.exists():
        todo("performance tracker missing")
        return False
    if not current.exists():
        todo("performance tracker has never refreshed; run python performance_tracker.py --no-google")
        return False
    try:
        from src.config import Config
        cfg = Config("config.story.yaml")
        if cfg.google_sheet_id:
            service_file = Path(cfg.google_service_account_file)
            if not service_file.is_absolute():
                service_file = ROOT / service_file
            if not service_file.exists():
                todo("GOOGLE_SHEET_ID is set but its service-account JSON is missing")
                return False
            ok("performance tracker refreshed; Google Sheets mirror configured")
        else:
            ok("performance tracker refreshed locally; Google Sheets mirror optional")
        return True
    except Exception as exc:
        todo(f"performance tracker configuration failed: {exc}")
        return False


def check_content_alignment():
    """Detect the split between generic tool videos and the ECHO story series."""
    series_path = ROOT / "content" / "echo100" / "series.json"
    runner_path = ROOT / "run_daily.ps1"
    if series_path.exists() and runner_path.exists():
        try:
            import json
            series = json.loads(series_path.read_text(encoding="utf-8"))
            runner = runner_path.read_text(encoding="utf-8")
            direct_story_runner = "story_main.py" in runner
            growth_runner = ROOT / "growth_controller.py"
            adaptive_story_runner = (
                "growth_controller.py" in runner
                and growth_runner.exists()
                and 'Config("config.story.yaml")' in growth_runner.read_text(encoding="utf-8")
            )
            if (series.get("canon_status") == "locked"
                    and series.get("episode_rules", {}).get("allow_stock_video") is False
                    and (direct_story_runner or adaptive_story_runner)):
                ok("ECHO//100 canon is locked; active daily controller uses config.story.yaml with stock footage blocked")
                return True
        except Exception:
            pass
    try:
        from src.config import Config
        niche = str(Config().get("channel", "niche", default="")).lower()
    except Exception:
        niche = ""
    has_story_assets = (ROOT / "assets" / "story" / "echo100").exists() or \
        (ROOT / "assets" / "episodes" / "echo100").exists()
    story_words = ("story", "series", "animated", "fiction", "mystery")
    if has_story_assets and not any(word in niche for word in story_words):
        todo("content strategy split: config/topics use AI-tool videos while ECHO//100 uses fiction")
        return False
    ok("channel niche, topic queue, and visual system are aligned")
    return True


def main():
    print("\n=== AI Creative Explorer — setup check ===\n")
    print("Machine:")
    results = [check_python(), check_ffmpeg(), check_packages(), check_offline_voice()]
    print("\nKeys:")
    results += [check_env_file(), check_llm(), check_pexels()]
    print("\nYouTube:")
    results += [check_youtube()]
    print("         Note: OAuth apps left in Testing issue 7-day refresh tokens.")

    print("\nAutomation:")
    results += [check_scheduler()]
    results += [check_performance_tracker()]

    print("\nContent:")
    results += [check_content_alignment()]

    done, total = sum(results), len(results)
    pct = round(done / total * 100)
    print(f"\n  Setup: {done}/{total} checks passed — {pct}% complete")
    if pct == 100:
        print("\n  All green! Safe test:     python story_main.py --dry-run --preview")
        print("  Private draft now:        python story_main.py")
        print("  Daily runner:             run_daily.ps1 (PRIVATE review drafts only)")
    else:
        print("\n  Fix the first [TODO] above, then run me again.")
    print()


if __name__ == "__main__":
    main()
