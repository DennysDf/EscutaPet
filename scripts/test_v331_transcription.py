from __future__ import annotations

import os
import stat
import sys
import tempfile
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
handle, database_path = tempfile.mkstemp(prefix="escutapet_v331_", suffix=".sqlite3")
os.close(handle); os.unlink(database_path)
os.environ.update(DATABASE_URL=f"sqlite:///{database_path}", AUTO_SEED_DEMO="1", REDIS_ENABLED="0", SECRET_KEY="test-secret-key-with-more-than-thirty-two-characters")

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import BASE_DIR
from app.database import SessionLocal
from app.main import app
from app.models import Conversation, ConversationMessage, Lead, LeadSegment, MediaAsset, Segment, TranscriptionConfig, TranscriptionJob
from app.services.engine import add_conversation_message
from app.services.transcription import process_transcription_once


def check(value, message):
    if not value: raise AssertionError(message)


with tempfile.TemporaryDirectory(prefix="escutapet_fake_whisper_") as tool_directory:
    tool_root = Path(tool_directory)
    fake_whisper = tool_root / "whisper-cli"
    fake_model = tool_root / "ggml-base-q5_1.bin"
    fake_whisper.write_text(
        "#!/usr/bin/env python3\nimport pathlib,sys\nargs=sys.argv\nout=args[args.index('-of')+1]\npathlib.Path(out+'.txt').write_text('Reclamei do banheiro e da limpeza.',encoding='utf-8')\n",
        encoding="utf-8",
    )
    fake_whisper.chmod(fake_whisper.stat().st_mode | stat.S_IEXEC)
    fake_model.write_bytes(b"modelo-de-teste")
    media_root = BASE_DIR / "data" / "media"
    media_root.mkdir(parents=True, exist_ok=True)
    incoming_file = media_root / "v331-incoming.wav"
    outgoing_file = media_root / "v331-outgoing.wav"
    for audio_file in (incoming_file, outgoing_file):
        with wave.open(str(audio_file), "wb") as audio:
            audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(16000); audio.writeframes(b"\x00\x00" * 1600)
    try:
        with TestClient(app) as client:
            check(client.post("/login", data={"username": "admin", "password": "admin123"}, follow_redirects=False).status_code == 303, "login falhou")
            settings = client.get("/configuracoes")
            check(settings.status_code == 200 and "Áudios · transcrição local" in settings.text, "configuração de transcrição não renderizou")
            with SessionLocal() as db:
                config = db.get(TranscriptionConfig, 1)
                config.enabled = True; config.executable_path = str(fake_whisper); config.model_path = str(fake_model)
                config.ffmpeg_path = None; config.transcribe_received = True; config.transcribe_sent = False
                segment = Segment(name="Reclamou da limpeza", kind="smart", keywords_json='["banheiro", "limpeza"]', min_confidence=.8)
                lead = Lead(name="Contato áudio", phone="5562000000001", phone_normalized="5562000000001", consent_research=True)
                conversation = Conversation(identity_key=lead.phone_normalized, phone_normalized=lead.phone_normalized, lead=lead)
                db.add_all([segment, lead, conversation]); db.flush()
                incoming_message = add_conversation_message(db, conversation, direction="in", content="[audio]", content_type="audio", external_id="audio-in")
                outgoing_message = add_conversation_message(db, conversation, direction="out", content="[audio]", content_type="audio", external_id="audio-out")
                db.flush()
                incoming_asset = MediaAsset(conversation_message_id=incoming_message.id, type="audio", local_path="media/v331-incoming.wav", mime_type="audio/wav", download_status="saved")
                outgoing_asset = MediaAsset(conversation_message_id=outgoing_message.id, type="audio", local_path="media/v331-outgoing.wav", mime_type="audio/wav", download_status="saved")
                db.add_all([incoming_asset, outgoing_asset]); db.commit()
                incoming_id, outgoing_id, lead_id, segment_id = incoming_asset.id, outgoing_asset.id, lead.id, segment.id

            result = process_transcription_once()
            with SessionLocal() as db:
                worker_error = db.get(TranscriptionConfig, 1).last_error
            check(result["processed"] == 1, f"áudio recebido não foi processado: {result} · {worker_error}")
            with SessionLocal() as db:
                incoming = db.get(MediaAsset, incoming_id); outgoing = db.get(MediaAsset, outgoing_id)
                check(incoming.transcription_status == "completed" and "banheiro" in incoming.transcript_text.lower(), "transcrição não foi preservada")
                check(outgoing.transcription_status == "skipped", "áudio enviado foi transcrito sem autorização")
                check(db.scalar(select(LeadSegment).where(LeadSegment.lead_id == lead_id, LeadSegment.segment_id == segment_id)), "transcrição não segmentou o lead")
                check(db.scalar(select(TranscriptionJob).where(TranscriptionJob.media_asset_id == incoming_id)).status == "completed", "job não foi concluído")
    finally:
        incoming_file.unlink(missing_ok=True)
        outgoing_file.unlink(missing_ok=True)

print("OK - EscutaPet 3.3.3: fila isolada, transcrição, política de saída e segmentação validadas.")
