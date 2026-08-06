from __future__ import annotations

import ipaddress
import json
import mimetypes
import secrets
import socket
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import BASE_DIR
from ..models import MediaAsset, ZapiConfig, utcnow


BLOCKED_EXTENSIONS = {".exe", ".bat", ".cmd", ".msi", ".js", ".vbs", ".scr", ".ps1", ".com"}
MEDIA_ROOT = BASE_DIR / "data" / "media"


def register_media(
    db: Session,
    media: dict,
    *,
    media_type: str,
    conversation_message_id: int | None = None,
    survey_answer_id: int | None = None,
) -> MediaAsset:
    source_url = str(media.get("source_url") or "").strip() or None
    config = db.get(ZapiConfig, 1)
    expires_at = utcnow() + timedelta(days=30) if source_url else None
    row = MediaAsset(
        conversation_message_id=conversation_message_id,
        survey_answer_id=survey_answer_id,
        type=media_type,
        source_url=source_url,
        mime_type=str(media.get("mime_type") or "")[:160] or None,
        file_name=str(media.get("file_name") or "")[:240] or None,
        caption=str(media.get("caption") or "")[:5000] or None,
        duration_seconds=_float_or_none(media.get("duration_seconds")),
        latitude=_float_or_none(media.get("latitude")),
        longitude=_float_or_none(media.get("longitude")),
        address=str(media.get("address") or "")[:500] or None,
        download_status="pending" if source_url and config and config.download_received_media else "not_applicable",
        expires_at=expires_at,
        metadata_json=json.dumps(media.get("metadata") or {}, ensure_ascii=False, default=str)[:25000],
    )
    db.add(row)
    db.flush()
    return row


def store_outbound_media(
    db: Session,
    data: bytes,
    *,
    file_name: str,
    mime_type: str | None,
    media_type: str,
    conversation_message_id: int,
    caption: str = "",
) -> MediaAsset:
    """Armazena anexo humano localmente antes de entrar na fila de envio."""
    config = db.get(ZapiConfig, 1)
    max_bytes = max(1, config.max_media_mb if config else 50) * 1024 * 1024
    if not data:
        raise ValueError("Escolha um arquivo antes de enviar.")
    if len(data) > max_bytes:
        raise ValueError(f"Arquivo maior que o limite configurado de {max_bytes // (1024 * 1024)} MB.")
    clean_name = Path(file_name or "arquivo").name[:220] or "arquivo"
    suffix = Path(clean_name).suffix.lower()
    if suffix in BLOCKED_EXTENSIONS:
        raise ValueError("Este tipo de arquivo não é permitido.")
    guessed = mimetypes.guess_extension((mime_type or "").split(";", 1)[0]) or suffix or ".bin"
    if guessed in BLOCKED_EXTENSIONS:
        raise ValueError("Este tipo de arquivo não é permitido.")
    row = MediaAsset(
        conversation_message_id=conversation_message_id,
        type=media_type,
        mime_type=(mime_type or mimetypes.guess_type(clean_name)[0] or "application/octet-stream")[:160],
        file_name=clean_name,
        caption=caption[:5000] or None,
        size_bytes=len(data),
        download_status="saved",
        metadata_json=json.dumps({"origin": "outbound_upload"}, ensure_ascii=False),
    )
    db.add(row); db.flush()
    target_dir = MEDIA_ROOT / "outbound" / utcnow().strftime("%Y") / utcnow().strftime("%m")
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{row.id}-{secrets.token_hex(12)}{guessed}"
    target.write_bytes(data)
    row.local_path = str(target.relative_to(BASE_DIR / "data"))
    return row


def media_as_data_url(asset: MediaAsset) -> str | None:
    path = local_media_path(asset)
    if not path:
        return None
    import base64
    payload = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{asset.mime_type or 'application/octet-stream'};base64,{payload}"


def _float_or_none(value):
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _safe_remote_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            return False
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
        for address in addresses:
            ip = ipaddress.ip_address(address[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_unspecified:
                return False
        return True
    except (OSError, ValueError):
        return False


def _extension(asset: MediaAsset, content_type: str | None) -> str:
    original = Path(asset.file_name or "").suffix.lower()
    if original and original not in BLOCKED_EXTENSIONS and len(original) <= 10:
        return original
    mime = (content_type or asset.mime_type or "").split(";", 1)[0].strip()
    extension = mimetypes.guess_extension(mime) or {
        "audio/ogg": ".ogg",
        "image/webp": ".webp",
        "application/pdf": ".pdf",
    }.get(mime, ".bin")
    return extension if extension not in BLOCKED_EXTENSIONS else ".bin"


def download_pending_media(db: Session, *, limit: int = 10) -> dict[str, int]:
    stats = {"media_saved": 0, "media_failed": 0}
    config = db.get(ZapiConfig, 1)
    if not config or not config.download_received_media:
        return stats
    max_bytes = max(1, config.max_media_mb or 50) * 1024 * 1024
    rows = db.scalars(
        select(MediaAsset)
        .where(MediaAsset.download_status == "pending", MediaAsset.source_url.is_not(None))
        .order_by(MediaAsset.id)
        .limit(limit)
    ).all()
    for asset in rows:
        if asset.expires_at and asset.expires_at <= utcnow():
            asset.download_status = "expired"
            stats["media_failed"] += 1
            db.commit()
            continue
        target: Path | None = None
        asset.download_status = "downloading"
        db.commit()
        try:
            if not _safe_remote_url(asset.source_url or ""):
                raise ValueError("URL de mídia não permitida.")
            with httpx.stream("GET", asset.source_url, timeout=httpx.Timeout(60.0, connect=12.0), follow_redirects=False) as response:
                response.raise_for_status()
                declared = int(response.headers.get("content-length") or 0)
                if declared > max_bytes:
                    raise ValueError("Mídia excede o tamanho permitido.")
                extension = _extension(asset, response.headers.get("content-type"))
                target_dir = MEDIA_ROOT / utcnow().strftime("%Y") / utcnow().strftime("%m")
                target_dir.mkdir(parents=True, exist_ok=True)
                target = target_dir / f"{asset.id}-{secrets.token_hex(12)}{extension}"
                written = 0
                with target.open("wb") as handle:
                    for chunk in response.iter_bytes(64 * 1024):
                        written += len(chunk)
                        if written > max_bytes:
                            raise ValueError("Mídia excede o tamanho permitido.")
                        handle.write(chunk)
            asset.local_path = str(target.relative_to(BASE_DIR / "data"))
            asset.size_bytes = written
            asset.mime_type = (response.headers.get("content-type") or asset.mime_type or "")[:160] or None
            asset.download_status = "saved"
            stats["media_saved"] += 1
        except Exception as exc:
            try:
                if target and target.exists():
                    target.unlink()
            except OSError:
                pass
            asset.download_status = "failed"
            metadata = json.loads(asset.metadata_json or "{}")
            metadata["download_error"] = str(exc)[:500]
            asset.metadata_json = json.dumps(metadata, ensure_ascii=False, default=str)
            stats["media_failed"] += 1
        db.commit()
    return stats


def prune_old_media(db: Session, *, limit: int = 50) -> dict[str, int]:
    stats = {"media_pruned": 0}
    config = db.get(ZapiConfig, 1)
    if not config:
        return stats
    cutoff = utcnow() - timedelta(days=max(30, config.media_retention_days or 365))
    rows = db.scalars(
        select(MediaAsset)
        .where(
            MediaAsset.download_status == "saved",
            MediaAsset.local_path.is_not(None),
            MediaAsset.created_at < cutoff,
        )
        .order_by(MediaAsset.created_at)
        .limit(limit)
    ).all()
    for asset in rows:
        path = local_media_path(asset)
        try:
            if path:
                path.unlink()
            asset.local_path = None
            asset.download_status = "pruned"
            stats["media_pruned"] += 1
        except OSError:
            continue
    if rows:
        db.commit()
    return stats


def local_media_path(asset: MediaAsset) -> Path | None:
    if not asset.local_path:
        return None
    candidate = (BASE_DIR / "data" / asset.local_path).resolve()
    root = MEDIA_ROOT.resolve()
    if root not in candidate.parents or not candidate.is_file():
        return None
    return candidate
