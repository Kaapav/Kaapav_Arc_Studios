"""Upload the finished video to YouTube via the Data API v3.

First run opens a browser to authorize (OAuth). The refresh token is cached at
credentials/token.json so every run after that is fully unattended — which is
what makes the daily scheduler hands-off.
"""
from pathlib import Path
import random
import time
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from .config import ROOT

# 'youtube' scope (manage account) is needed to flip privacy after upload, so the
# review step can publish a private draft. 'upload' alone can't update videos.
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]


def resolve_client_secret(cfg) -> Path:
    """Find a valid installed-app OAuth JSON even after Google renames downloads."""
    configured = ROOT / cfg.yt_client_secret
    if configured.exists():
        return configured
    credentials_dir = ROOT / "credentials"
    candidates = [credentials_dir / "client_secret.json"]
    candidates.extend(sorted(
        credentials_dir.glob("client_secret*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    ))
    seen = set()
    for candidate in candidates:
        if candidate in seen or not candidate.exists():
            continue
        seen.add(candidate)
        try:
            import json
            payload = json.loads(candidate.read_text(encoding="utf-8"))
            if isinstance(payload.get("installed"), dict):
                return candidate
        except Exception:
            continue
    raise FileNotFoundError(
        f"Missing Desktop OAuth client JSON. Expected {configured} or "
        f"credentials/client_secret.json."
    )


def _get_service(
    cfg,
    verify_channel: bool = True,
    allow_interactive: bool = False,
    force_account_selection: bool = False,
):
    token_path = ROOT / cfg.yt_token
    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not allow_interactive:
                raise RuntimeError(
                    "YouTube OAuth token is missing or invalid. Run: "
                    "python authorize_youtube.py --switch-channel"
                )
            secret_path = resolve_client_secret(cfg)
            flow = InstalledAppFlow.from_client_secrets_file(str(secret_path), SCOPES)
            # run_console works on headless servers; run_local_server on desktop
            try:
                oauth_options = {
                    "access_type": "offline",
                    "prompt": "consent",
                }
                if cfg.youtube_login_hint:
                    oauth_options["login_hint"] = cfg.youtube_login_hint
                creds = flow.run_local_server(
                    port=0,
                    timeout_seconds=300,
                    **oauth_options,
                )
            except Exception as exc:
                raise RuntimeError(
                    "Browser OAuth did not complete within five minutes. "
                    "Run authorize_youtube.py again and finish the browser approval."
                ) from exc
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json(), encoding="utf-8")
    service = build("youtube", "v3", credentials=creds)
    if verify_channel:
        verify_upload_target(cfg, service)
    return service


def verify_upload_target(cfg, service=None) -> dict:
    """Fail closed when OAuth belongs to a different YouTube channel."""
    if service is None:
        service = _get_service(cfg, verify_channel=False, allow_interactive=False)
    response = service.channels().list(part="snippet", mine=True).execute()
    items = response.get("items", [])
    if not items:
        raise RuntimeError("OAuth account has no accessible YouTube channel")
    channel = items[0]
    expected = str(cfg.get("youtube", "expected_channel_id", default="") or "").strip()
    if expected and channel.get("id") != expected:
        actual_title = channel.get("snippet", {}).get("title", "unknown")
        raise RuntimeError(
            f"Wrong YouTube channel authorized: {actual_title} ({channel.get('id')}); "
            f"expected {expected}. Run: python authorize_youtube.py --switch-channel"
        )
    return {
        "id": channel.get("id"),
        "title": channel.get("snippet", {}).get("title", ""),
    }


def build_upload_body(cfg, meta: dict, privacy_override: str = None,
                      publish_at: str = None) -> tuple[dict, str, str | None]:
    """Build the API payload and resolved privacy without making a request."""
    yt = cfg["youtube"]
    tags = list(dict.fromkeys(
        (meta.get("tags") or [])
        + yt.get("upload_default_tags", [])
        + yt.get("tags_extra", [])
    ))
    title = meta["title"][: yt.get("title_max", 100)]
    publish_at = publish_at or meta.get("publish_at")
    privacy = "private" if publish_at else (privacy_override or yt.get("privacy", "private"))
    description = str(meta.get("description", "") or "").strip()
    footer = str(yt.get("upload_default_description_footer", "") or "").strip()
    if footer and footer not in description:
        description = f"{description}\n\n{footer}" if description else footer

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": str(yt.get("category_id", "27")),
            "defaultLanguage": str(yt.get("default_language", "en")),
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": bool(yt.get("made_for_kids", False)),
            "containsSyntheticMedia": bool(
                (meta.get("safety") or {}).get("disclosure_needed", True)
            ),
        },
    }
    if publish_at:
        body["status"]["publishAt"] = publish_at
    return body, privacy, publish_at


def _remote_contract(body: dict) -> dict:
    snippet = body.get("snippet") or {}
    return {
        "snippet": {
            "title": snippet.get("title", ""),
            "description": snippet.get("description", ""),
            "tags": list(snippet.get("tags") or []),
            "categoryId": str(snippet.get("categoryId") or ""),
            "defaultLanguage": str(snippet.get("defaultLanguage") or ""),
        }
    }


def _verify_remote_schedule(service, video_id: str, body: dict, publish_at: str,
                            attempts: int = 6) -> tuple[bool, str]:
    """Confirm the server holds the exact metadata and future schedule."""
    expected = _remote_contract(body)["snippet"]
    last = "remote video was not returned"
    for attempt in range(attempts):
        response = service.videos().list(
            part="snippet,status", id=video_id, maxResults=1,
        ).execute()
        items = response.get("items", [])
        if items:
            item = items[0]
            snippet = item.get("snippet") or {}
            status = item.get("status") or {}
            checks = {
                "privacy": status.get("privacyStatus") == "private",
                "publish_at": status.get("publishAt") == publish_at,
                "title": snippet.get("title", "") == expected["title"],
                "description": snippet.get("description", "") == expected["description"],
                "tags": set(snippet.get("tags") or []) == set(expected["tags"]),
                "category": str(snippet.get("categoryId") or "") == expected["categoryId"],
                "language": str(snippet.get("defaultLanguage") or "") == expected["defaultLanguage"],
                "made_for_kids": not bool(status.get("madeForKids", False)),
            }
            if all(checks.values()):
                return True, "confirmed"
            last = "remote contract mismatch: " + ",".join(
                name for name, passed in checks.items() if not passed
            )
        if attempt < attempts - 1:
            time.sleep(min(2 ** attempt, 30))
    return False, last


def _hold_private(service, cfg, video_id: str) -> None:
    service.videos().update(part="status", body={
        "id": video_id,
        "status": {
            "privacyStatus": "private",
            "selfDeclaredMadeForKids": bool(cfg["youtube"].get("made_for_kids", False)),
            "containsSyntheticMedia": True,
        },
    }).execute()


def upload_video(cfg, video_path: Path, meta: dict, privacy_override: str = None,
                 publish_at: str = None) -> dict:
    """Upload and return {"id": videoId, "url": url, "privacy": status}.

    privacy_override lets the review flow force 'private' regardless of config.
    """
    # This check lives at the irreversible boundary on purpose.  Even an old
    # caller or shortcut cannot upload bytes that did not pass the current gate.
    from .release_audit import assert_fresh_audit, run_publish_audit
    from . import release_ledger

    video_path = Path(video_path).resolve()
    if privacy_override == "public":
        raise RuntimeError(
            "Immediate public upload is disabled. Strict policy requires a private "
            "upload with a future publish_at slot."
        )
    release_ledger.assert_not_uploaded(video_path, meta)
    service = _get_service(cfg, verify_channel=False)
    channel = verify_upload_target(cfg, service)
    audit = run_publish_audit(
        cfg,
        video_path,
        meta,
        publish_at=publish_at,
        online_channel=channel,
    )
    assert_fresh_audit(cfg, video_path, meta, audit)
    body, privacy, publish_at = build_upload_body(
        cfg, meta, privacy_override=privacy_override, publish_at=publish_at
    )

    media_body = MediaFileUpload(str(video_path), chunksize=-1, resumable=True,
                                 mimetype="video/*")
    request = service.videos().insert(part="snippet,status", body=body,
                                      media_body=media_body)
    response = None
    retries = 0
    while response is None:
        status = None
        try:
            status, response = request.next_chunk()
        except Exception as exc:
            status_code = getattr(getattr(exc, "resp", None), "status", None)
            retryable = status_code in {408, 429, 500, 502, 503, 504}
            if status_code is None and isinstance(exc, (TimeoutError, ConnectionError, OSError)):
                retryable = True
            if not retryable or retries >= 5:
                raise
            delay = min(60, (2 ** retries) + random.random())
            retries += 1
            print(f"  [upload] transient failure; retry {retries}/5 in {delay:.1f}s ({exc})")
            time.sleep(delay)
            continue
        if status:
            print(f"  [upload] {int(status.progress() * 100)}%")
    vid = response["id"]
    url = f"https://youtu.be/{vid}"
    thumbnail_path = meta.get("thumbnail_path")
    thumbnail_set = False
    thumbnail_error = None
    if thumbnail_path and Path(thumbnail_path).exists():
        try:
            set_thumbnail(service, vid, Path(thumbnail_path))
            thumbnail_set = True
            print(f"  [upload] Thumbnail set -> {thumbnail_path}")
        except Exception as exc:
            thumbnail_error = f"{type(exc).__name__}: {exc}"[:500]
    if not thumbnail_set:
        # Never let the server-side publishAt fire with a missing custom
        # thumbnail.  Keep the already-created upload private and resume it by ID.
        _hold_private(service, cfg, vid)
        print(f"  [upload] HELD PRIVATE: custom thumbnail not confirmed ({thumbnail_error})")
        result = {
            "id": vid, "url": url, "privacy": "private", "publish_at": None,
            "audit_id": audit.get("audit_id"), "thumbnail_set": False,
            "schedule_confirmed": False, "status": "held_private_thumbnail",
            "thumbnail_error": thumbnail_error, "remote_contract": _remote_contract(body),
            "made_for_kids": bool(cfg["youtube"].get("made_for_kids", False)),
        }
        release_ledger.record(video_path, meta, result)
        return result
    if publish_at:
        confirmed, contract_error = _verify_remote_schedule(service, vid, body, publish_at)
        if not confirmed:
            _hold_private(service, cfg, vid)
            result = {
                "id": vid, "url": url, "privacy": "private", "publish_at": None,
                "audit_id": audit.get("audit_id"), "thumbnail_set": True,
                "schedule_confirmed": False, "status": "held_private_remote_contract",
                "remote_contract_error": contract_error,
                "remote_contract": _remote_contract(body),
                "made_for_kids": bool(cfg["youtube"].get("made_for_kids", False)),
            }
            release_ledger.record(video_path, meta, result)
            return result
    schedule_note = f", publishAt={publish_at}" if publish_at else ""
    print(f"  [upload] Done -> {url} (privacy={privacy}{schedule_note})")
    result = {
        "id": vid,
        "url": url,
        "privacy": privacy,
        "publish_at": publish_at,
        "audit_id": audit.get("audit_id"),
        "thumbnail_set": True,
        "schedule_confirmed": bool(publish_at),
        "status": "scheduled" if publish_at else "private_review",
        "remote_contract": _remote_contract(body),
        "made_for_kids": bool(cfg["youtube"].get("made_for_kids", False)),
    }
    from .youtube_playlists import route_release
    result["playlist"] = route_release(service, meta, vid)
    release_ledger.record(video_path, meta, result)
    return result


def set_thumbnail(service, video_id: str, thumbnail_path: Path, attempts: int = 5) -> None:
    """Set a custom thumbnail with bounded retries; raise if not confirmed."""
    last_error = None
    for attempt in range(attempts):
        try:
            body = MediaFileUpload(str(thumbnail_path), mimetype="image/jpeg")
            service.thumbnails().set(videoId=video_id, media_body=body).execute()
            return
        except Exception as exc:
            last_error = exc
            status_code = getattr(getattr(exc, "resp", None), "status", None)
            if status_code not in {408, 429, 500, 502, 503, 504} or attempt == attempts - 1:
                break
            time.sleep(min(30, (2 ** attempt) + random.random()))
    raise RuntimeError(f"Custom thumbnail could not be confirmed: {last_error}")


def set_video_privacy(cfg, video_id: str, privacy: str) -> dict:
    """Flip an already-uploaded video's privacy (e.g. private -> public on approval).

    Preserves made-for-kids so the update doesn't reset it. Returns the API status.
    """
    if privacy == "public":
        raise RuntimeError(
            "Immediate public release is disabled. Use schedule_video with a "
            "fresh strict publish audit and a future slot."
        )
    yt = cfg["youtube"]
    service = _get_service(cfg)
    body = {
        "id": video_id,
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": bool(yt.get("made_for_kids", False)),
            "containsSyntheticMedia": True,
        },
    }
    resp = service.videos().update(part="status", body=body).execute()
    print(f"  [publish] {video_id} -> {privacy}")
    return resp.get("status", {})


def schedule_video(cfg, video_id: str, publish_at: str, *, video_path: Path = None,
                   meta: dict = None) -> dict:
    """Schedule a never-published private video for server-side publication."""
    if video_path is None or meta is None:
        raise RuntimeError(
            "Strict scheduling requires the original local video and metadata for "
            "a fresh byte-level audit."
        )
    yt = cfg["youtube"]
    from .release_audit import assert_fresh_audit, run_publish_audit

    service = _get_service(cfg, verify_channel=False)
    channel = verify_upload_target(cfg, service)
    audit = run_publish_audit(
        cfg, Path(video_path), meta, publish_at=publish_at, online_channel=channel
    )
    assert_fresh_audit(cfg, Path(video_path), meta, audit)
    thumbnail_path = Path(meta.get("thumbnail_path") or "")
    if not thumbnail_path.exists():
        raise RuntimeError("Custom thumbnail is missing; scheduling remains blocked")
    set_thumbnail(service, video_id, thumbnail_path)
    body, _, _ = build_upload_body(cfg, meta, privacy_override="private", publish_at=publish_at)
    body["id"] = video_id
    resp = service.videos().update(part="snippet,status", body=body).execute()
    confirmed, contract_error = _verify_remote_schedule(service, video_id, body, publish_at)
    if not confirmed:
        _hold_private(service, cfg, video_id)
        result = {
            "id": video_id, "privacy": "private", "publish_at": None,
            "thumbnail_set": True, "schedule_confirmed": False,
            "audit_id": audit.get("audit_id"), "status": "held_private_remote_contract",
            "remote_contract_error": contract_error,
            "remote_contract": _remote_contract(body),
            "made_for_kids": bool(yt.get("made_for_kids", False)),
        }
        from . import release_ledger
        release_ledger.record(Path(video_path), meta, result)
        return result
    print(f"  [schedule] {video_id} -> {publish_at}")
    result = {
        "id": video_id,
        "privacy": (resp.get("status") or {}).get("privacyStatus", "private"),
        "publish_at": publish_at,
        "thumbnail_set": True,
        "schedule_confirmed": True,
        "audit_id": audit.get("audit_id"),
        "status": "scheduled",
        "remote_contract": _remote_contract(body),
        "made_for_kids": bool(yt.get("made_for_kids", False)),
    }
    from .youtube_playlists import route_release
    result["playlist"] = route_release(service, meta, video_id)
    from . import release_ledger
    release_ledger.record(Path(video_path), meta, result)
    return result
