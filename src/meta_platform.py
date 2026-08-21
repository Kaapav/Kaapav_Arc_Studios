"""Meta Page and Instagram publishing with strict QC and persistent recovery.

Secrets are read only from environment variables or an excluded credential
file. No token is ever written to analytics, logs, release results or errors.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import random
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import requests

from .config import ROOT
from . import platform_control


STATUS_PATH = ROOT / "analytics" / "meta_status.json"
QUEUE_PATH = ROOT / "analytics" / "meta_release_queue.json"
LEDGER_PATH = ROOT / "analytics" / "meta_release_ledger.json"
MEDIA_GRANTS_PATH = ROOT / "analytics" / "meta_media_grants.json"
MEDIA_SECRET_PATH = ROOT / "credentials" / "meta_media_signing_secret.bin"
DEFAULT_TOKEN_FILE = ROOT / "credentials" / "meta_system_user_token.txt"
TRANSIENT_HTTP = {408, 429, 500, 502, 503, 504}
PLATFORMS = ("facebook", "instagram")


class MetaError(RuntimeError):
    """A safe Meta error whose message never contains credentials."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp() -> str:
    return _now().isoformat().replace("+00:00", "Z")


def _read(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def token_path() -> Path:
    raw = os.getenv("META_SYSTEM_USER_TOKEN_FILE", "").strip()
    if not raw:
        return DEFAULT_TOKEN_FILE
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def load_token() -> str:
    direct = os.getenv("META_SYSTEM_USER_TOKEN", "").strip()
    if direct:
        return direct
    path = token_path()
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise MetaError(f"Meta credential file is missing: {path}") from exc
    if len(value) < 40 or any(character.isspace() for character in value):
        raise MetaError("Meta credential file is empty or malformed")
    return value


def credential_present() -> bool:
    if os.getenv("META_SYSTEM_USER_TOKEN", "").strip():
        return True
    try:
        return token_path().is_file() and token_path().stat().st_size >= 40
    except OSError:
        return False


def _safe_api_error(response: requests.Response) -> MetaError:
    code = response.status_code
    kind = "MetaApiError"
    message = "request rejected"
    try:
        error = (response.json() or {}).get("error") or {}
        kind = str(error.get("type") or kind)
        message = str(error.get("message") or message)
        api_code = error.get("code")
        subcode = error.get("error_subcode")
        suffix = f" api_code={api_code}" if api_code is not None else ""
        suffix += f" subcode={subcode}" if subcode is not None else ""
    except (ValueError, TypeError):
        suffix = ""
    message = re.sub(r"(?i)(access[_ -]?token|app[_ -]?secret)\s*[:=]\s*\S+", r"\1=[redacted]", message)
    return MetaError(f"Meta HTTP {code} {kind}: {message[:350]}{suffix}")


class MetaClient:
    def __init__(self, cfg, token: str | None = None):
        self.cfg = cfg
        self.token = token or load_token()
        version = str(cfg.get("meta", "graph_version", default="v23.0") or "v23.0")
        self.version = version if version.startswith("v") else f"v{version}"
        self.base = f"https://graph.facebook.com/{self.version}"
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "KAAPAV-ARC-Automation/1.0"})

    def request(
        self, method: str, path: str, *, token: str | None = None,
        params: dict[str, Any] | None = None, data: Any = None,
        files: Any = None, headers: dict[str, str] | None = None,
        timeout: int = 90, attempts: int = 5,
    ) -> dict[str, Any]:
        url = path if path.startswith("https://") else f"{self.base}/{path.lstrip('/')}"
        auth = token or self.token
        request_headers = {"Authorization": f"Bearer {auth}"}
        request_headers.update(headers or {})
        last_error: Exception | None = None
        for attempt in range(max(1, attempts)):
            try:
                response = self.session.request(
                    method, url, params=params, data=data, files=files,
                    headers=request_headers, timeout=timeout,
                )
                if response.status_code < 400:
                    if not response.content:
                        return {}
                    try:
                        payload = response.json()
                    except ValueError as exc:
                        raise MetaError(f"Meta returned non-JSON HTTP {response.status_code}") from exc
                    return payload if isinstance(payload, dict) else {"data": payload}
                error = _safe_api_error(response)
                if response.status_code not in TRANSIENT_HTTP or attempt == attempts - 1:
                    raise error
                last_error = error
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_error = MetaError(f"Meta network failure: {type(exc).__name__}")
                if attempt == attempts - 1:
                    raise last_error from exc
            time.sleep(min(30.0, (2 ** attempt) + random.random()))
        raise last_error or MetaError("Meta request failed")

    def discover(self) -> dict[str, Any]:
        expected_id = str(self.cfg.get("meta", "expected_page_id", default="") or "").strip()
        try:
            response = self.request("GET", "/me/accounts", params={
                "fields": "id,name,access_token,tasks,instagram_business_account{id,username,name,followers_count,media_count},connected_instagram_account{id,username,name,followers_count,media_count}",
                "limit": 100,
            })
            pages = response.get("data") or []
        except MetaError:
            # A system-user token may expose assigned business assets only
            # through the Business edge instead of /me/accounts.
            pages = []
        business_id = str(self.cfg.get("meta", "business_id", default="") or "").strip()
        if business_id:
            try:
                business_pages = self.request("GET", f"/{business_id}/owned_pages", params={
                    "fields": "id,name,access_token,tasks,instagram_business_account{id,username,name,followers_count,media_count},connected_instagram_account{id,username,name,followers_count,media_count}",
                    "limit": 100,
                }).get("data") or []
                known = {str(item.get("id")) for item in pages}
                pages.extend(item for item in business_pages if str(item.get("id")) not in known)
            except MetaError:
                # Some valid user/page tokens cannot query the Business edge;
                # /me/accounts remains authoritative for those token types.
                pass
        if expected_id and not any(str(item.get("id")) == expected_id for item in pages):
            try:
                direct_page = self.request("GET", f"/{expected_id}", params={
                    "fields": "id,name,access_token,tasks,instagram_business_account{id,username,name,followers_count,media_count},connected_instagram_account{id,username,name,followers_count,media_count}",
                })
                if str(direct_page.get("id") or "") == expected_id:
                    pages.append(direct_page)
            except MetaError:
                # Keep the fail-closed available-page check below authoritative.
                pass
        expected_name = str(self.cfg.get("meta", "expected_page_name", default="KAAPAV ARC Studios") or "").strip().casefold()
        page = next((item for item in pages if expected_id and str(item.get("id")) == expected_id), None)
        if page is None:
            page = next((item for item in pages if str(item.get("name") or "").strip().casefold() == expected_name), None)
        if page is None:
            available = [str(item.get("name") or item.get("id") or "unknown") for item in pages]
            raise MetaError(f"Expected Facebook Page was not returned; available={available[:10]}")
        instagram = page.get("instagram_business_account") or page.get("connected_instagram_account") or {}
        page_token = str(page.get("access_token") or self.token)
        return {
            "page_id": str(page.get("id") or ""),
            "page_name": str(page.get("name") or ""),
            "page_tasks": list(page.get("tasks") or []),
            "page_token": page_token,
            "instagram_id": str(instagram.get("id") or ""),
            "instagram_username": str(instagram.get("username") or ""),
            "instagram_name": str(instagram.get("name") or ""),
            "instagram_followers": int(instagram.get("followers_count") or 0),
            "instagram_media_count": int(instagram.get("media_count") or 0),
        }


def health_check(cfg, *, write: bool = True) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": 1,
        "checked_at": _stamp(),
        "credential_present": credential_present(),
        "status": "not_configured",
    }
    if not payload["credential_present"]:
        payload["detail"] = "Meta token is not installed in the automation credential store"
    else:
        try:
            account = MetaClient(cfg).discover()
            required_task = bool(set(account.get("page_tasks") or []) & {"CREATE_CONTENT", "MANAGE"})
            instagram_ready = bool(account.get("instagram_id"))
            facebook_state = "ready" if required_task else "permission_issue"
            instagram_state = "ready" if required_task and instagram_ready else (
                "not_linked" if required_task else "permission_issue"
            )
            payload.update({
                "status": "ready" if facebook_state == instagram_state == "ready" else (
                    "partial" if facebook_state == "ready" else "permission_issue"
                ),
                "page": {
                    "id": account["page_id"], "name": account["page_name"],
                    "tasks": account["page_tasks"],
                },
                "instagram": {
                    "id": account["instagram_id"], "username": account["instagram_username"],
                    "name": account["instagram_name"],
                },
                "platforms": {
                    "facebook": {
                        "status": facebook_state,
                        "detail": "Facebook Page content tasks verified" if required_task else "Page token lacks a content-management task",
                    },
                    "instagram": {
                        "status": instagram_state,
                        "detail": "Linked Instagram professional account verified" if instagram_ready else "Facebook Page is not linked to an Instagram professional account",
                    },
                },
                "detail": (
                    "Facebook Page and linked Instagram professional account verified"
                    if facebook_state == instagram_state == "ready"
                    else "Facebook is ready; Instagram professional account link is missing"
                    if facebook_state == "ready"
                    else "Page token lacks a content-management task"
                ),
            })
        except Exception as exc:
            payload.update({"status": "error", "detail": str(exc)[:500], "error_type": type(exc).__name__})
    if write:
        _write(STATUS_PATH, payload)
    return payload


def _media_secret() -> bytes:
    MEDIA_SECRET_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        value = MEDIA_SECRET_PATH.read_bytes()
        if len(value) >= 32:
            return value
    except OSError:
        pass
    value = secrets.token_bytes(32)
    try:
        descriptor = os.open(MEDIA_SECRET_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(value)
    except FileExistsError:
        return MEDIA_SECRET_PATH.read_bytes()
    return value


def _grant_signature(grant_id: str, expires: int, digest: str) -> str:
    message = f"{grant_id}.{expires}.{digest}".encode("ascii")
    raw = hmac.new(_media_secret(), message, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def issue_media_grant(cfg, video_path: Path, *, audit_id: str, ttl_hours: int = 6) -> str:
    video = Path(video_path).resolve()
    allowed = (ROOT / "output" / "story").resolve()
    if allowed not in video.parents or not video.is_file():
        raise MetaError("Only audited studio output videos can receive a Meta media grant")
    digest = _sha256(video)
    grant_id = secrets.token_urlsafe(18)
    expires = int(time.time() + max(1, ttl_hours) * 3600)
    grants = _read(MEDIA_GRANTS_PATH, {"schema_version": 1, "grants": {}})
    now = int(time.time())
    grants["grants"] = {
        key: value for key, value in (grants.get("grants") or {}).items()
        if int(value.get("expires") or 0) >= now
    }
    grants["grants"][grant_id] = {
        "path": str(video), "sha256": digest, "expires": expires,
        "audit_id": audit_id, "created_at": _stamp(),
    }
    _write(MEDIA_GRANTS_PATH, grants)
    signature = _grant_signature(grant_id, expires, digest)
    base_url = str(cfg.get("meta", "public_media_base_url", default="https://yt.kaapav.com") or "").rstrip("/")
    return f"{base_url}/media/{grant_id}/{signature}/{video.name}"


def resolve_media_grant(route: str) -> Path | None:
    match = re.fullmatch(r"/media/([A-Za-z0-9_-]{12,})/([A-Za-z0-9_-]{32,})/([^/]+)", route)
    if not match:
        return None
    grant_id, signature, filename = match.groups()
    grant = (_read(MEDIA_GRANTS_PATH, {}).get("grants") or {}).get(grant_id) or {}
    expires = int(grant.get("expires") or 0)
    digest = str(grant.get("sha256") or "")
    if expires < int(time.time()) or not digest:
        return None
    if not hmac.compare_digest(signature, _grant_signature(grant_id, expires, digest)):
        return None
    path = Path(str(grant.get("path") or "")).resolve()
    allowed = (ROOT / "output" / "story").resolve()
    if allowed not in path.parents or path.name != filename or not path.is_file():
        return None
    if _sha256(path) != digest:
        return None
    return path


def build_caption(meta: dict[str, Any], platform: str) -> str:
    title = str(meta.get("title") or "").strip()
    description = str(meta.get("description") or "").strip()
    cleaned = []
    for line in description.splitlines():
        lower = line.casefold()
        if "youtube.com" in lower or lower.startswith("subscribe"):
            continue
        cleaned.append(line.rstrip())
    body = "\n".join(cleaned).strip()
    tags = ["KAAPAVARCStudios"]
    for value in meta.get("tags") or []:
        tag = re.sub(r"[^A-Za-z0-9]", "", str(value))
        if tag and tag.casefold() not in {item.casefold() for item in tags}:
            tags.append(tag)
    tag_limit = 8 if platform == "instagram" else 5
    hashtags = " ".join(f"#{tag}" for tag in tags[:tag_limit])
    cta = (
        "Follow KAAPAV ARC Studios and save this episode. The next chapter is already waiting."
        if platform == "instagram"
        else "Follow KAAPAV ARC Studios and share this episode. The next chapter is already waiting."
    )
    caption = f"{title}\n\n{body}\n\n{cta}\n\n{hashtags}".strip()
    limit = 2200 if platform == "instagram" else 5000
    return caption[:limit].rstrip()


def _ledger() -> dict[str, Any]:
    return _read(LEDGER_PATH, {"schema_version": 1, "releases": []})


def _record_release(item: dict[str, Any], result: dict[str, Any]) -> None:
    state = _ledger()
    releases = state.setdefault("releases", [])
    key = item["key"]
    releases[:] = [entry for entry in releases if entry.get("key") != key]
    releases.append({
        "key": key, "platform": item["platform"], "series_id": item.get("series_id"),
        "episode": item.get("episode"), "release_kind": item.get("release_kind"),
        "video_sha256": item.get("video_sha256"), "audit_id": item.get("audit_id"),
        "remote_id": result.get("id"), "url": result.get("url"),
        "published_at": result.get("published_at") or _stamp(), "status": "published",
    })
    state["updated_at"] = _stamp()
    _write(LEDGER_PATH, state)


def _already_published(key: str) -> bool:
    return any(entry.get("key") == key and entry.get("status") == "published" for entry in _ledger().get("releases") or [])


def _item_key(platform: str, entry: dict[str, Any]) -> str:
    identity = entry.get("episode_id") or f"{entry.get('series_id')}:{entry.get('episode')}:{entry.get('release_kind')}"
    return f"{platform}:{identity}"


def reconcile_release_queue(cfg) -> dict[str, Any]:
    """Queue only future, strictly audited releases. Old public work is never backfilled."""
    from . import release_ledger

    queue = _read(QUEUE_PATH, {"schema_version": 1, "items": []})
    if bool(cfg.get("meta", "owner_authorized_relaunch", default=False)):
        items = queue.get("items") or []
        return {
            "status": "owner_authorized_relaunch",
            "added": 0,
            "queued": sum(item.get("status") not in {"published", "held_missed_slot", "manual_reconciliation_required"} for item in items),
        }
    by_key = {str(item.get("key")): item for item in queue.get("items") or []}
    now = _now()
    policy_start = int(cfg.get("autopilot", "policy_applies_from_episode", default=11))
    added = 0
    for entry in release_ledger.sync_from_outputs().get("releases") or []:
        publish_at = _parse_time(entry.get("publish_at"))
        if publish_at is None or publish_at <= now:
            continue
        episode = int(entry.get("episode") or 0)
        if episode < 1:
            continue
        if entry.get("release_kind", "short") == "short" and episode < policy_start:
            continue
        video = Path(str(entry.get("video_path") or ""))
        metadata_path = video.parent / "metadata.json"
        audit_path = video.parent / "prepublish_audit.json"
        if not video.is_file() or not metadata_path.is_file() or not audit_path.is_file() or not entry.get("audit_id"):
            continue
        for platform in PLATFORMS:
            key = _item_key(platform, entry)
            if key in by_key or _already_published(key):
                continue
            item = {
                "key": key, "platform": platform, "series_id": entry.get("series_id"),
                "episode_id": entry.get("episode_id"), "episode": episode,
                "release_kind": entry.get("release_kind", "short"),
                "title": entry.get("title"), "video_path": str(video.resolve()),
                "metadata_path": str(metadata_path.resolve()), "audit_path": str(audit_path.resolve()),
                "video_sha256": entry.get("video_sha256"), "audit_id": entry.get("audit_id"),
                "publish_at": publish_at.isoformat().replace("+00:00", "Z"),
                "status": "queued", "attempts": 0, "created_at": _stamp(),
            }
            by_key[key] = item
            added += 1
    queue["items"] = sorted(by_key.values(), key=lambda item: (str(item.get("publish_at")), str(item.get("platform"))))
    queue["updated_at"] = _stamp()
    _write(QUEUE_PATH, queue)
    return {"status": "ready", "added": added, "queued": sum(item.get("status") == "queued" for item in queue["items"])}


def _checkpoint(key: str, **updates: Any) -> dict[str, Any]:
    queue = _read(QUEUE_PATH, {"schema_version": 1, "items": []})
    found = None
    for item in queue.get("items") or []:
        if item.get("key") == key:
            item.update(updates)
            item["updated_at"] = _stamp()
            found = item
            break
    if found is None:
        raise MetaError(f"Meta queue item disappeared: {key}")
    queue["updated_at"] = _stamp()
    _write(QUEUE_PATH, queue)
    return found


def _publish_facebook(client: MetaClient, account: dict[str, Any], item: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    page_id, page_token = account["page_id"], account["page_token"]
    video = Path(item["video_path"])
    caption = build_caption(meta, "facebook")
    if item.get("release_kind") == "compilation":
        _checkpoint(item["key"], status="facebook_regular_uploading")
        with video.open("rb") as handle:
            response = client.request(
                "POST", f"/{page_id}/videos", token=page_token,
                data={"title": str(meta.get("title") or "")[:255], "description": caption, "published": "true"},
                files={"source": (video.name, handle, "video/mp4")}, timeout=900, attempts=3,
            )
        remote_id = str(response.get("id") or "")
    else:
        status = str(item.get("status") or "")
        remote_id = str(item.get("remote_id") or "")
        upload_url = str(item.get("upload_url") or "")
        if status == "facebook_finishing" and remote_id:
            try:
                detail = client.request("GET", f"/{remote_id}", token=page_token, params={"fields": "id,permalink_url"}, attempts=2)
                if detail.get("id"):
                    return {"id": remote_id, "url": detail.get("permalink_url") or f"https://www.facebook.com/{page_id}/videos/{remote_id}", "published_at": _stamp()}
            except Exception:
                pass
        if status not in {"facebook_upload_started", "facebook_uploaded", "facebook_finishing"}:
            started = client.request("POST", f"/{page_id}/video_reels", token=page_token, params={"upload_phase": "start"})
            remote_id = str(started.get("video_id") or "")
            upload_url = str(started.get("upload_url") or "")
            if not remote_id or not upload_url:
                raise MetaError("Facebook did not return a Reel upload session")
            _checkpoint(item["key"], status="facebook_upload_started", remote_id=remote_id, upload_url=upload_url)
            status = "facebook_upload_started"
        if status == "facebook_upload_started":
            if not remote_id or not upload_url:
                raise MetaError("Facebook resumable upload checkpoint is incomplete")
            size = video.stat().st_size
            with video.open("rb") as handle:
                client.request(
                    "POST", upload_url, token=page_token, data=handle,
                    headers={"Authorization": f"OAuth {page_token}", "offset": "0", "file_size": str(size),
                             "Content-Type": "application/octet-stream"}, timeout=900, attempts=3,
                )
            _checkpoint(item["key"], status="facebook_uploaded", remote_id=remote_id, upload_url=upload_url)
        _checkpoint(item["key"], status="facebook_finishing", remote_id=remote_id, upload_url=upload_url)
        client.request("POST", f"/{page_id}/video_reels", token=page_token, params={
            "upload_phase": "finish", "video_id": remote_id, "video_state": "PUBLISHED",
            "description": caption, "title": str(meta.get("title") or "")[:255],
        })
    if not remote_id:
        raise MetaError("Facebook publish response did not include a video ID")
    return {"id": remote_id, "url": f"https://www.facebook.com/{page_id}/videos/{remote_id}", "published_at": _stamp()}


def _publish_instagram(client: MetaClient, cfg, account: dict[str, Any], item: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    ig_id, page_token = account["instagram_id"], account["page_token"]
    caption = build_caption(meta, "instagram")
    status_name = str(item.get("status") or "")
    container_id = str(item.get("container_id") or "")
    if status_name == "instagram_publishing":
        try:
            recent = client.request("GET", f"/{ig_id}/media", token=page_token, params={
                "fields": "id,caption,timestamp,permalink", "limit": 25,
            })
            match = next((row for row in recent.get("data") or [] if str(row.get("caption") or "") == caption), None)
            if match:
                return {"id": str(match.get("id")), "url": match.get("permalink"), "published_at": match.get("timestamp") or _stamp()}
        except Exception:
            pass
    if status_name not in {"instagram_container_created", "instagram_container_ready", "instagram_publishing"}:
        grant_url = issue_media_grant(cfg, Path(item["video_path"]), audit_id=str(item.get("audit_id") or ""))
        created = client.request("POST", f"/{ig_id}/media", token=page_token, data={
            "media_type": "REELS", "video_url": grant_url,
            "caption": caption, "share_to_feed": "true",
        })
        container_id = str(created.get("id") or "")
        if not container_id:
            raise MetaError("Instagram did not return a media container ID")
        _checkpoint(item["key"], status="instagram_container_created", container_id=container_id)
        status_name = "instagram_container_created"
    if not container_id:
        raise MetaError("Instagram resumable container checkpoint is incomplete")
    deadline = time.monotonic() + 12 * 60
    if status_name != "instagram_container_ready" and status_name != "instagram_publishing":
        while time.monotonic() < deadline:
            status = client.request("GET", f"/{container_id}", token=page_token, params={"fields": "status_code,status"})
            code = str(status.get("status_code") or "").upper()
            if code == "FINISHED":
                break
            if code in {"ERROR", "EXPIRED"}:
                raise MetaError(f"Instagram container failed with status {code}")
            time.sleep(5)
        else:
            raise MetaError("Instagram container processing exceeded 12 minutes")
        _checkpoint(item["key"], status="instagram_container_ready", container_id=container_id)
    _checkpoint(item["key"], status="instagram_publishing", container_id=container_id)
    published = client.request("POST", f"/{ig_id}/media_publish", token=page_token, data={"creation_id": container_id})
    media_id = str(published.get("id") or "")
    if not media_id:
        raise MetaError("Instagram publish response did not include a media ID")
    try:
        detail = client.request("GET", f"/{media_id}", token=page_token, params={"fields": "permalink,timestamp"})
    except Exception:
        detail = {}
    return {"id": media_id, "url": detail.get("permalink"), "published_at": detail.get("timestamp") or _stamp()}


def process_due(cfg, *, now: datetime | None = None, limit: int = 4) -> dict[str, Any]:
    """Publish due items only; pause and platform controls are hard gates."""
    current = (now or _now()).astimezone(timezone.utc)
    result = {"status": "ready", "published": [], "failed": [], "held": []}
    if (ROOT / str(cfg.get("autopilot", "emergency_pause_file", default="analytics/PAUSE_AUTOPILOT"))).exists():
        result.update({"status": "master_gate_closed", "detail": "Global automation is paused"})
        return result
    controls = platform_control.summary()
    enabled_platforms = [name for name in PLATFORMS if bool(controls[name].get("enabled"))]
    if not enabled_platforms:
        result["status"] = "platforms_disabled"
        return result
    health = health_check(cfg)
    if health.get("status") != "ready":
        result.update({"status": "credential_or_asset_error", "detail": health.get("detail")})
        return result
    client = MetaClient(cfg)
    account = client.discover()
    queue = _read(QUEUE_PATH, {"schema_version": 1, "items": []})
    grace = timedelta(minutes=int(cfg.get("meta", "late_publish_grace_minutes", default=30)))
    processed = 0
    for raw in queue.get("items") or []:
        if processed >= max(0, limit):
            break
        item = dict(raw)
        if item.get("platform") not in enabled_platforms or item.get("status") in {"published", "held_missed_slot", "manual_reconciliation_required"}:
            continue
        due = _parse_time(item.get("publish_at"))
        retry_at = _parse_time(item.get("retry_at"))
        if due is None or current < due or (retry_at and current < retry_at):
            continue
        processed += 1
        if current > due + grace:
            _checkpoint(item["key"], status="held_missed_slot", error="publish window expired; no blind late post")
            result["held"].append(item["key"])
            continue
        try:
            from .release_audit import assert_persisted_release_evidence
            metadata = _read(Path(item["metadata_path"]), {})
            audit = assert_persisted_release_evidence(
                Path(item["video_path"]), metadata, Path(item["audit_path"]),
                expected_audit_id=str(item.get("audit_id") or ""),
            )
            if _sha256(Path(item["video_path"])) != str(item.get("video_sha256") or ""):
                raise MetaError("Queued video hash no longer matches the release ledger")
            if item.get("status") in {"queued", "retry_wait"}:
                item = _checkpoint(item["key"], status=f"{item['platform']}_publishing", attempts=int(item.get("attempts") or 0) + 1)
            if item["platform"] == "facebook":
                remote = _publish_facebook(client, account, item, metadata)
            else:
                remote = _publish_instagram(client, cfg, account, item, metadata)
            item["audit_id"] = audit["audit_id"]
            _record_release(item, remote)
            _checkpoint(item["key"], status="published", remote_id=remote.get("id"), url=remote.get("url"), published_at=remote.get("published_at"), error=None)
            result["published"].append({"key": item["key"], "id": remote.get("id"), "url": remote.get("url")})
        except Exception as exc:
            latest = next((row for row in (_read(QUEUE_PATH, {"items": []}).get("items") or []) if row.get("key") == item["key"]), item)
            attempts = max(1, int(latest.get("attempts") or item.get("attempts") or 0))
            retry = current + timedelta(minutes=min(15, 2 ** min(attempts, 4)))
            uncertain = latest.get("status") == "facebook_regular_uploading"
            next_status = "manual_reconciliation_required" if uncertain else "retry_wait" if retry <= due + grace else "held_missed_slot"
            _checkpoint(item["key"], status=next_status, attempts=attempts,
                        retry_at=retry.isoformat().replace("+00:00", "Z"),
                        error_type=type(exc).__name__, error=str(exc)[:500])
            result["failed"].append({"key": item["key"], "error_type": type(exc).__name__, "error": str(exc)[:300]})
    if result["failed"]:
        result["status"] = "recovery_required"
    result["checked_at"] = _stamp()
    return result


def queue_summary() -> dict[str, Any]:
    items = _read(QUEUE_PATH, {"items": []}).get("items") or []
    ledger = _ledger().get("releases") or []
    by_platform: dict[str, dict[str, Any]] = {}
    for platform in PLATFORMS:
        relevant = [item for item in items if item.get("platform") == platform]
        releases = [item for item in ledger if item.get("platform") == platform]
        failures = [item for item in relevant if item.get("status") in {"retry_wait", "held_missed_slot", "manual_reconciliation_required"}]
        next_item = next((item for item in relevant if item.get("status") not in {"published", "held_missed_slot", "manual_reconciliation_required"}), None)
        by_platform[platform] = {
            "queued": sum(item.get("status") not in {"published", "held_missed_slot", "manual_reconciliation_required"} for item in relevant),
            "published": len(releases), "failures": len(failures),
            "next_publish_at": next_item.get("publish_at") if next_item else None,
            "last_error": failures[-1].get("error") if failures else None,
        }
    return by_platform
