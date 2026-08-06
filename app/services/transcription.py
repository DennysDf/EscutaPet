from __future__ import annotations

import os
import secrets
import shutil
import subprocess
import tempfile
import time
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import PROJECT_DIR
from ..database import SessionLocal
from ..models import (
    Conversation,
    ConversationMessage,
    MediaAsset,
    SurveyAnswer,
    TranscriptionConfig,
    TranscriptionJob,
    utcnow,
)
from .media import local_media_path
from .segmentation import segment_from_answer, segment_from_conversation


TOOLS_ROOT = PROJECT_DIR / "tools"


def _configured_file(value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = PROJECT_DIR / path
    return path.resolve() if path.is_file() else None


def _first_file(patterns: list[str]) -> Path | None:
    for pattern in patterns:
        for path in TOOLS_ROOT.rglob(pattern) if TOOLS_ROOT.exists() else []:
            if path.is_file():
                return path.resolve()
    return None


def resolve_components(config: TranscriptionConfig | None) -> dict[str, Path | None]:
    executable = _configured_file(config.executable_path if config else None) or _first_file([
        "whisper-cli.exe", "main.exe", "whisper-cli", "main",
    ])
    model = _configured_file(config.model_path if config else None) or _first_file([
        "ggml-base-q5_1.bin", "ggml-model-whisper-base-q5_1.bin", "*base*q5*.bin", "ggml-base.bin",
    ])
    ffmpeg = _configured_file(config.ffmpeg_path if config else None) or _first_file(["ffmpeg.exe", "ffmpeg"])
    if not ffmpeg:
        found = shutil.which("ffmpeg")
        ffmpeg = Path(found).resolve() if found else None
    return {"executable": executable, "model": model, "ffmpeg": ffmpeg}


def transcription_diagnostics(config: TranscriptionConfig | None) -> dict:
    components = resolve_components(config)
    enabled = bool(config and config.enabled)
    ready = bool(components["executable"] and components["model"])
    return {
        "enabled": enabled,
        "ready": ready,
        "executable": str(components["executable"] or ""),
        "model": str(components["model"] or ""),
        "ffmpeg": str(components["ffmpeg"] or ""),
        "message": (
            "Motor pronto para transcrever."
            if ready and components["ffmpeg"]
            else "Whisper pronto; FFmpeg ausente, somente WAV compatível poderá ser processado."
            if ready
            else "Coloque whisper-cli e o modelo em tools\\whisper ou informe os caminhos abaixo."
        ),
    }


def enqueue_ready_audio(db: Session, *, limit: int = 30) -> int:
    config = db.get(TranscriptionConfig, 1)
    if not config or not config.enabled:
        return 0
    assets = db.scalars(
        select(MediaAsset)
        .where(
            MediaAsset.type == "audio",
            MediaAsset.download_status == "saved",
            MediaAsset.local_path.is_not(None),
            MediaAsset.transcription_status.in_(["not_requested", "waiting"]),
        )
        .order_by(MediaAsset.id)
        .limit(limit)
    ).all()
    created = 0
    for asset in assets:
        existing = db.scalar(select(TranscriptionJob.id).where(TranscriptionJob.media_asset_id == asset.id))
        if existing:
            continue
        message = db.get(ConversationMessage, asset.conversation_message_id) if asset.conversation_message_id else None
        if message and message.direction == "out" and not config.transcribe_sent:
            asset.transcription_status = "skipped"
            continue
        if (not message or message.direction != "out") and not config.transcribe_received:
            asset.transcription_status = "skipped"
            continue
        db.add(TranscriptionJob(
            media_asset_id=asset.id,
            conversation_message_id=asset.conversation_message_id,
            survey_answer_id=asset.survey_answer_id,
            status="pending",
            available_at=utcnow(),
        ))
        asset.transcription_status = "pending"
        created += 1
    if created:
        db.commit()
    return created


def _normalize_audio(source: Path, target: Path, ffmpeg: Path | None, timeout: int) -> None:
    if not ffmpeg and source.suffix.lower() == ".wav":
        shutil.copyfile(source, target)
        return
    if not ffmpeg:
        raise RuntimeError("FFmpeg não encontrado para converter este formato de áudio.")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    result = subprocess.run(
        [str(ffmpeg), "-y", "-i", str(source), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(target)],
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=flags,
        check=False,
    )
    if result.returncode != 0 or not target.is_file():
        detail = (result.stderr or result.stdout or "Falha ao converter o áudio.")[-700:]
        raise RuntimeError(detail)


def _transcribe(source: Path, config: TranscriptionConfig, components: dict[str, Path | None]) -> tuple[str, float]:
    timeout = max(90, min(3600, config.max_duration_seconds * 4))
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="escutapet_transcription_") as directory:
        temporary = Path(directory)
        wav = temporary / "audio.wav"
        output = temporary / "transcript"
        _normalize_audio(source, wav, components["ffmpeg"], timeout)
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        command = [
            str(components["executable"]), "-m", str(components["model"]), "-f", str(wav),
            "-l", (config.language or "pt")[:12], "-t", str(max(1, min(8, config.threads or 2))),
            "-otxt", "-of", str(output), "-nt", "-np",
        ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, creationflags=flags, check=False)
        transcript_file = output.with_suffix(".txt")
        transcript = transcript_file.read_text(encoding="utf-8", errors="replace").strip() if transcript_file.is_file() else ""
        if result.returncode != 0 or not transcript:
            detail = (result.stderr or result.stdout or "O Whisper não retornou uma transcrição.")[-900:]
            raise RuntimeError(detail)
    return transcript[:25000], round(time.monotonic() - started, 3)


def _finish_success(db: Session, job: TranscriptionJob, transcript: str, elapsed: float, model: Path) -> None:
    asset = db.get(MediaAsset, job.media_asset_id)
    if not asset:
        raise RuntimeError("Mídia vinculada à transcrição não existe.")
    config = db.get(TranscriptionConfig, 1)
    job.status = "completed"
    job.transcript_text = transcript
    job.detected_language = (config.language or "pt")[:20]
    job.model_name = model.name[:120]
    job.processing_seconds = elapsed
    job.completed_at = utcnow()
    job.error_message = None
    asset.transcription_status = "completed"
    asset.transcript_text = transcript
    asset.transcript_language = job.detected_language
    asset.transcribed_at = utcnow()
    answer = db.get(SurveyAnswer, asset.survey_answer_id or job.survey_answer_id) if (asset.survey_answer_id or job.survey_answer_id) else None
    if answer:
        answer.transcript_text = transcript
        if answer.execution and answer.execution.lead_id and answer.question and answer.execution.questionnaire.auto_segment:
            segment_from_answer(db, answer.execution.lead_id, answer.question, transcript)
    elif config.segment_transcripts and job.conversation_message_id:
        message = db.get(ConversationMessage, job.conversation_message_id)
        conversation = db.get(Conversation, message.conversation_id) if message else None
        if message and message.direction == "in" and conversation and conversation.lead_id:
            segment_from_conversation(
                db, conversation.lead_id, transcript,
                origin="audio_transcript", reason_label=f"Transcrição do áudio da mensagem #{message.id}",
            )
    if job.conversation_message_id:
        message = db.get(ConversationMessage, job.conversation_message_id)
        if message: message.status_at = utcnow()
    config.last_job_at = utcnow()
    config.last_error = None


def process_transcription_once() -> dict[str, int | str | bool]:
    stats: dict[str, int | str | bool] = {"queued": 0, "processed": 0, "failed": 0, "ready": False}
    with SessionLocal() as db:
        config = db.get(TranscriptionConfig, 1)
        if not config:
            return stats
        config.last_heartbeat_at = utcnow()
        stats["queued"] = enqueue_ready_audio(db)
        stale = utcnow() - timedelta(minutes=20)
        for item in db.scalars(select(TranscriptionJob).where(TranscriptionJob.status == "processing", TranscriptionJob.started_at < stale)).all():
            item.status = "pending"; item.worker_token = None; item.available_at = utcnow()
        diagnostics = transcription_diagnostics(config)
        components = resolve_components(config)
        stats["ready"] = diagnostics["ready"]
        if not config.enabled:
            db.commit(); return stats
        if not diagnostics["ready"]:
            config.last_error = diagnostics["message"]
            db.commit(); return stats
        job = db.scalar(
            select(TranscriptionJob)
            .where(TranscriptionJob.status == "pending", TranscriptionJob.available_at <= utcnow())
            .order_by(TranscriptionJob.available_at, TranscriptionJob.id)
            .limit(1)
        )
        if not job:
            db.commit(); return stats
        asset = db.get(MediaAsset, job.media_asset_id)
        source = local_media_path(asset) if asset else None
        job.status = "processing"; job.started_at = utcnow(); job.worker_token = secrets.token_urlsafe(18); job.attempt += 1
        if asset: asset.transcription_status = "processing"
        db.commit()
        try:
            if not asset or not source:
                raise RuntimeError("Arquivo local do áudio não foi encontrado.")
            if asset.duration_seconds and asset.duration_seconds > config.max_duration_seconds:
                raise RuntimeError(f"Áudio acima do limite de {config.max_duration_seconds} segundos.")
            transcript, elapsed = _transcribe(source, config, components)
            _finish_success(db, job, transcript, elapsed, components["model"])
            stats["processed"] = 1
        except Exception as exc:
            detail = str(exc)[:1200]
            job.error_message = detail; job.worker_token = None
            if job.attempt < 3:
                job.status = "pending"; job.available_at = utcnow() + timedelta(minutes=3 * job.attempt)
                if asset: asset.transcription_status = "pending"
            else:
                job.status = "failed"; job.completed_at = utcnow()
                if asset: asset.transcription_status = "failed"
            config.last_error = detail
            if job.conversation_message_id:
                message = db.get(ConversationMessage, job.conversation_message_id)
                if message: message.status_at = utcnow()
            stats["failed"] = 1
        db.commit()
    return stats


def run_transcription_worker() -> None:
    print("EscutaPet Worker de Transcrição iniciado. Pressione Ctrl+C para parar.")
    while True:
        try:
            result = process_transcription_once()
            time.sleep(1 if result.get("processed") else 5)
        except KeyboardInterrupt:
            break
        except Exception:
            time.sleep(5)
