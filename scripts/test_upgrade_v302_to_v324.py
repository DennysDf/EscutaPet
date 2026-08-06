from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))
handle, database_path = tempfile.mkstemp(prefix="escutapet_upgrade_v302_", suffix=".sqlite3")
os.close(handle)
os.unlink(database_path)

# Estrutura de entry_flows existente na 3.0.2, antes dos campos da jornada visual.
with sqlite3.connect(database_path) as connection:
    connection.executescript("""
    CREATE TABLE entry_flows (
      id INTEGER PRIMARY KEY, name VARCHAR(160) NOT NULL, description TEXT,
      status VARCHAR(20), profiles_json TEXT, welcome_title VARCHAR(180), welcome_text TEXT,
      allow_existing_lookup BOOLEAN, collect_city BOOLEAN, collect_neighborhood BOOLEAN,
      allow_no_pet BOOLEAN, max_pets INTEGER, service_options_json TEXT,
      service_status_options_json TEXT, phone_verification_mode VARCHAR(30),
      phone_verification_timeout INTEGER, allow_manual_confirmation BOOLEAN,
      consent_terms_version VARCHAR(40), consent_research_text TEXT, consent_marketing_text TEXT,
      immediate_questionnaire_id INTEGER, immediate_channel VARCHAR(30),
      confirmed_questionnaire_id INTEGER, confirmed_channel VARCHAR(30),
      followup_questionnaire_id INTEGER, followup_delay_value INTEGER,
      followup_delay_unit VARCHAR(20), followup_requires_confirmation BOOLEAN,
      closing_title VARCHAR(180), closing_text TEXT, created_at DATETIME, updated_at DATETIME
    );
    CREATE TABLE media_assets (
      id INTEGER PRIMARY KEY, conversation_message_id INTEGER, survey_answer_id INTEGER,
      type VARCHAR(30) NOT NULL, source_url TEXT, local_path TEXT, mime_type VARCHAR(160),
      file_name VARCHAR(240), caption TEXT, size_bytes INTEGER, duration_seconds FLOAT,
      latitude FLOAT, longitude FLOAT, address VARCHAR(500), download_status VARCHAR(30),
      expires_at DATETIME, metadata_json TEXT, created_at DATETIME, updated_at DATETIME
    );
    INSERT INTO entry_flows (
      id,name,status,profiles_json,welcome_title,welcome_text,allow_existing_lookup,
      collect_city,collect_neighborhood,allow_no_pet,max_pets,service_options_json,
      service_status_options_json,phone_verification_mode,phone_verification_timeout,
      allow_manual_confirmation,consent_terms_version,consent_research_text,
      consent_marketing_text,immediate_channel,confirmed_channel,followup_delay_value,
      followup_delay_unit,followup_requires_confirmation,closing_title,closing_text,
      created_at,updated_at
    ) VALUES (
      1,'Fluxo preservado da 3.0.2','active','["kiosk"]','Olá','Teste',1,1,1,1,10,
      '[]','[]','send_continue',180,1,'1.0','Aceito','Aceito','none','none',7,'days',1,
      'Obrigado','Concluído',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP
    );
    """)

os.environ["DATABASE_URL"] = f"sqlite:///{database_path}"
os.environ["AUTO_SEED_DEMO"] = "0"
os.environ["REDIS_ENABLED"] = "0"
os.environ["SECRET_KEY"] = "test-secret-key-with-more-than-thirty-two-characters"

from sqlalchemy import inspect
from app.database import SessionLocal, engine
from app.models import EntryFlow
from app.services.bootstrap import initialize_database

initialize_database()
columns = {item["name"] for item in inspect(engine).get_columns("entry_flows")}
required = {
    "registration_questionnaire_id", "revision", "last_edited_by_id",
    "consent_research_enabled", "consent_marketing_enabled", "consent_terms_enabled",
    "city_ids_json", "device_ids_json",
}
if not required.issubset(columns):
    raise AssertionError(f"colunas não migradas: {sorted(required - columns)}")
media_columns = {item["name"] for item in inspect(engine).get_columns("media_assets")}
transcription_columns = {"transcription_status", "transcript_text", "transcript_language", "transcribed_at"}
if not transcription_columns.issubset(media_columns):
    raise AssertionError(f"campos de transcrição não migrados: {sorted(transcription_columns - media_columns)}")
tables = set(inspect(engine).get_table_names())
if not {"transcription_config", "transcription_jobs"}.issubset(tables):
    raise AssertionError("tabelas da fila de transcrição não foram criadas")
with SessionLocal() as db:
    flow = db.get(EntryFlow, 1)
    if not flow or flow.name != "Fluxo preservado da 3.0.2":
        raise AssertionError("fluxo antigo não foi preservado")
    if flow.city_ids_json != "[]" or flow.device_ids_json != "[]":
        raise AssertionError("escopos novos não receberam padrão seguro")

print("OK - banco 3.0.2 atualizado para 3.3.3 com fluxos preservados e fila de transcrição criada.")
