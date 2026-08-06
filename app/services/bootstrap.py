from __future__ import annotations

import json
import secrets
from datetime import datetime

from sqlalchemy import func, inspect, select, text

from ..config import settings
from ..database import Base, SessionLocal, engine
from ..models import (
    City,
    Conversation,
    Device,
    EntryFlow,
    EntryFlowAction,
    Lead,
    LeadSegment,
    Pet,
    Question,
    Questionnaire,
    Segment,
    SegmentEvent,
    SystemSetting,
    TranscriptionConfig,
    User,
    WorkerState,
    WebhookEvent,
    ZapiConfig,
)
from .security import hash_password, normalize_phone
from .phone_migration import migrate_phone_identities


def _ensure_compatible_schema() -> None:
    """Small in-place compatibility for 2.0 databases; fresh installs already contain these columns."""
    inspector = inspect(engine)
    additions = {
        "system_settings": {
            "sidebar_color": "VARCHAR(16) NOT NULL DEFAULT '#071a2b'",
            "footer_text": "VARCHAR(240)",
            "logo_horizontal_file": "VARCHAR(100)",
            "logo_vertical_file": "VARCHAR(100)",
            "logo_icon_file": "VARCHAR(100)",
            "branding_version": "INTEGER NOT NULL DEFAULT 1",
        },
        "users": {
            "email": "VARCHAR(160)",
            "phone": "VARCHAR(40)",
            "avatar_color": "VARCHAR(16) NOT NULL DEFAULT '#0f766e'",
            "preferred_theme": "VARCHAR(20) NOT NULL DEFAULT 'system'",
            "navigation_compact": "BOOLEAN NOT NULL DEFAULT 0",
            "timezone_name": "VARCHAR(80)",
            "all_cities": "BOOLEAN NOT NULL DEFAULT 1",
            "city_ids_json": "TEXT NOT NULL DEFAULT '[]'",
            "device_ids_json": "TEXT NOT NULL DEFAULT '[]'",
            "chat_signature": "TEXT",
            "chat_signature_enabled": "BOOLEAN NOT NULL DEFAULT 0",
        },
        "leads": {
            "city_id": "INTEGER",
            "whatsapp_lid": "VARCHAR(100)",
            "whatsapp_display_name": "VARCHAR(160)",
            "whatsapp_chat_name": "VARCHAR(160)",
            "whatsapp_profile_photo_url": "TEXT",
            "whatsapp_about": "VARCHAR(500)",
            "whatsapp_identity_updated_at": "DATETIME",
            "whatsapp_identity_source": "VARCHAR(40)",
        },
        "questions": {
            "whatsapp_response_mode": "VARCHAR(24) NOT NULL DEFAULT 'auto'",
            "data_binding": "VARCHAR(60)",
            "active": "BOOLEAN NOT NULL DEFAULT 1",
            "archived_at": "DATETIME",
            "settings_json": "TEXT NOT NULL DEFAULT '{}'",
        },
        "questionnaire_version_questions": {
            "settings_json": "TEXT NOT NULL DEFAULT '{}'",
        },
        "questionnaires": {
            "seed_key": "VARCHAR(80)",
            "revision": "INTEGER NOT NULL DEFAULT 1",
            "last_edited_by_id": "INTEGER",
        },
        "message_queue": {
            "message_type": "VARCHAR(24) NOT NULL DEFAULT 'text'",
            "media_payload_json": "TEXT NOT NULL DEFAULT '{}'",
            "version_question_id": "INTEGER",
            "conversation_message_id": "INTEGER",
            "media_asset_id": "INTEGER",
            "reply_external_id": "VARCHAR(160)",
        },
        "survey_executions": {
            "questionnaire_version_id": "INTEGER",
            "collection_session_id": "INTEGER",
            "flow_action_id": "INTEGER",
            "pet_id": "INTEGER",
            "idempotency_key": "VARCHAR(220)",
            "context_json": "TEXT NOT NULL DEFAULT '{}'",
            "invalid_attempts": "INTEGER NOT NULL DEFAULT 0",
            "city_id": "INTEGER",
            "device_id": "INTEGER",
        },
        "survey_answers": {
            "content_type": "VARCHAR(30) NOT NULL DEFAULT 'text'",
            "version_question_id": "INTEGER",
            "transcript_text": "TEXT",
        },
        "conversations": {
            "identity_key": "VARCHAR(120)",
            "whatsapp_lid": "VARCHAR(100)",
            "internal_status": "VARCHAR(30) NOT NULL DEFAULT 'open'",
            "assigned_user_id": "INTEGER",
            "pinned": "BOOLEAN NOT NULL DEFAULT 0",
            "last_read_message_id": "INTEGER",
        },
        "conversation_messages": {
            "reference_external_id": "VARCHAR(160)",
            "status": "VARCHAR(24) NOT NULL DEFAULT 'received'",
            "status_at": "DATETIME",
            "error_message": "TEXT",
            "sender_user_id": "INTEGER",
            "reply_to_message_id": "INTEGER",
            "quoted_content": "VARCHAR(500)",
            "is_internal": "BOOLEAN NOT NULL DEFAULT 0",
        },
        "media_assets": {
            "transcription_status": "VARCHAR(24) NOT NULL DEFAULT 'not_requested'",
            "transcript_text": "TEXT",
            "transcript_language": "VARCHAR(20)",
            "transcribed_at": "DATETIME",
        },
        "devices": {
            "default_entry_flow_id": "INTEGER",
            "city_id": "INTEGER",
            "address": "VARCHAR(260)",
            "latitude": "FLOAT",
            "longitude": "FLOAT",
        },
        "collection_sessions": {
            "city_id": "INTEGER",
            "is_test": "BOOLEAN NOT NULL DEFAULT 0",
            "decisions_json": "TEXT NOT NULL DEFAULT '{}'",
        },
        "entry_flows": {
            "registration_questionnaire_id": "INTEGER",
            "revision": "INTEGER NOT NULL DEFAULT 1",
            "last_edited_by_id": "INTEGER",
            "consent_research_enabled": "BOOLEAN NOT NULL DEFAULT 1",
            "consent_marketing_enabled": "BOOLEAN NOT NULL DEFAULT 1",
            "consent_terms_enabled": "BOOLEAN NOT NULL DEFAULT 1",
            "city_ids_json": "TEXT NOT NULL DEFAULT '[]'",
            "device_ids_json": "TEXT NOT NULL DEFAULT '[]'",
        },
        "segment_automations": {
            "trigger_type": "VARCHAR(30) NOT NULL DEFAULT 'campaign'",
            "entry_delay_value": "INTEGER NOT NULL DEFAULT 0",
            "entry_delay_unit": "VARCHAR(20) NOT NULL DEFAULT 'hours'",
            "selection_strategy": "VARCHAR(30) NOT NULL DEFAULT 'single'",
            "distribution_mode": "VARCHAR(20) NOT NULL DEFAULT 'fixed'",
            "send_window_start": "INTEGER NOT NULL DEFAULT 540",
            "send_window_end": "INTEGER NOT NULL DEFAULT 1020",
            "timezone_name": "VARCHAR(80) NOT NULL DEFAULT 'America/Sao_Paulo'",
            "cooldown_days": "INTEGER NOT NULL DEFAULT 14",
            "max_cycles": "INTEGER",
            "cancel_on_exit": "BOOLEAN NOT NULL DEFAULT TRUE",
            "block_while_active": "BOOLEAN NOT NULL DEFAULT TRUE",
            "sample_mode": "VARCHAR(20) NOT NULL DEFAULT 'per_cycle'",
            "repeat_policy": "VARCHAR(30) NOT NULL DEFAULT 'cooldown'",
        },
        "entry_flow_actions": {
            "version_mode": "VARCHAR(30) NOT NULL DEFAULT 'latest_published'",
            "fixed_version_id": "INTEGER",
            "depends_on_action_id": "INTEGER",
            "condition_question_id": "INTEGER",
            "condition_operator": "VARCHAR(30)",
            "condition_value": "VARCHAR(300)",
            "conditions_json": "TEXT NOT NULL DEFAULT '[]'",
            "condition_logic": "VARCHAR(10) NOT NULL DEFAULT 'and'",
            "random_group": "VARCHAR(80)",
            "random_weight": "INTEGER NOT NULL DEFAULT 1",
            "fixed_scheduled_at": "DATETIME",
        },
        "zapi_config": {
            "send_endpoint_mode": "VARCHAR(20) NOT NULL DEFAULT 'automatic'",
            "manual_send_endpoint": "VARCHAR(1000)",
            "notify_sent_by_me": "BOOLEAN NOT NULL DEFAULT 0",
            "auto_read_message": "BOOLEAN NOT NULL DEFAULT 0",
            "remote_webhooks_ok": "BOOLEAN NOT NULL DEFAULT 0",
            "device_name": "VARCHAR(160)",
            "device_phone": "VARCHAR(40)",
            "last_webhook_at": "DATETIME",
            "download_received_media": "BOOLEAN NOT NULL DEFAULT 1",
            "max_media_mb": "INTEGER NOT NULL DEFAULT 50",
            "media_retention_days": "INTEGER NOT NULL DEFAULT 365",
        },
    }
    with engine.begin() as connection:
        for table_name, columns in additions.items():
            if table_name not in inspector.get_table_names():
                continue
            existing = {column["name"] for column in inspector.get_columns(table_name)}
            for name, ddl in columns.items():
                if name not in existing:
                    connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {name} {ddl}"))
        if "conversations" in inspector.get_table_names():
            connection.execute(text(
                "UPDATE conversations SET identity_key = COALESCE(identity_key, phone_normalized) "
                "WHERE identity_key IS NULL OR identity_key = ''"
            ))
        for statement in (
            "CREATE INDEX IF NOT EXISTS ix_survey_executions_questionnaire_version_id ON survey_executions (questionnaire_version_id)",
            "CREATE INDEX IF NOT EXISTS ix_survey_answers_version_question_id ON survey_answers (version_question_id)",
            "CREATE INDEX IF NOT EXISTS ix_message_queue_version_question_id ON message_queue (version_question_id)",
            "CREATE INDEX IF NOT EXISTS ix_entry_flow_actions_fixed_version_id ON entry_flow_actions (fixed_version_id)",
            "CREATE INDEX IF NOT EXISTS ix_conversation_messages_cursor ON conversation_messages (conversation_id, occurred_at, id)",
            "CREATE INDEX IF NOT EXISTS ix_message_queue_conversation_message_id ON message_queue (conversation_message_id)",
            "CREATE INDEX IF NOT EXISTS ix_media_assets_transcription_status ON media_assets (transcription_status)",
            "CREATE INDEX IF NOT EXISTS ix_transcription_jobs_due ON transcription_jobs (status, available_at)",
            "CREATE INDEX IF NOT EXISTS ix_segment_automations_trigger ON segment_automations (status, trigger_type)",
            "CREATE INDEX IF NOT EXISTS ix_segment_automation_questionnaires_order ON segment_automation_questionnaires (automation_id, position)",
            "CREATE INDEX IF NOT EXISTS ix_segment_automation_enrollments_due ON segment_automation_enrollments (status, next_due_at)",
            "CREATE INDEX IF NOT EXISTS ix_survey_executions_city_id ON survey_executions (city_id)",
            "CREATE INDEX IF NOT EXISTS ix_survey_executions_device_id ON survey_executions (device_id)",
        ):
            connection.execute(text(statement))


def initialize_database() -> None:
    Base.metadata.create_all(bind=engine)
    _ensure_compatible_schema()
    with SessionLocal() as db:
        if not db.get(SystemSetting, 1):
            db.add(SystemSetting(id=1))
        if not db.get(ZapiConfig, 1):
            db.add(ZapiConfig(
                id=1,
                webhook_secret=secrets.token_urlsafe(24),
                public_base_url=settings.public_base_url or None,
            ))
        if not db.scalar(select(func.count(User.id))):
            db.add(User(name="Administrador", username="admin", password_hash=hash_password("admin123"), role="admin"))
        if not db.get(WorkerState, 1):
            db.add(WorkerState(id=1, status="stopped"))
        if not db.get(TranscriptionConfig, 1):
            db.add(TranscriptionConfig(id=1))
        db.commit()
        # Automações antigas continuam válidas e ganham o questionário principal na nova coleção.
        db.execute(text(
            "INSERT INTO segment_automation_questionnaires (automation_id, questionnaire_id, position, weight, active) "
            "SELECT a.id, a.questionnaire_id, 1, 1, TRUE FROM segment_automations a "
            "WHERE NOT EXISTS (SELECT 1 FROM segment_automation_questionnaires q WHERE q.automation_id = a.id)"
        ))
        db.commit()
        setting = db.get(SystemSetting, 1)
        migrate_phone_identities(db, setting.default_country_code if setting else "55")
        migrate_cities(db)
        if settings.auto_seed_demo:
            seed_demo(db)
            seed_entry_flow(db)
        ensure_legacy_questionnaires_and_flow(db)
        ensure_structured_registration_questionnaire(db)
        migrate_entry_flow_actions(db)
        backfill_segment_history(db)
        from .versioning import migrate_questionnaire_versions
        migrate_questionnaire_versions(db)
        recover_received_callbacks(db)


def backfill_segment_history(db) -> None:
    """Cria o marco inicial sem inventar movimentações anteriores à 3.2.5."""
    existing = set(db.execute(select(SegmentEvent.segment_id, SegmentEvent.lead_id).where(SegmentEvent.event_type == "entered")).all())
    changed = False
    for link in db.scalars(select(LeadSegment)).all():
        if (link.segment_id, link.lead_id) in existing: continue
        db.add(SegmentEvent(segment_id=link.segment_id, lead_id=link.lead_id, event_type="entered", origin="migration", confidence=link.confidence, reason="Vínculo existente antes do histórico da versão 3.2.5.", occurred_at=link.created_at))
        changed = True
    if changed: db.commit()


def migrate_cities(db) -> None:
    """Create city records from the free-text 2.2 data without losing historical labels."""
    existing_names = {
        (item.name.casefold(), item.state): item
        for item in db.scalars(select(City)).all()
    }
    changed = False
    lead_cities = db.scalars(
        select(Lead.city).where(Lead.city.is_not(None), Lead.city != "").distinct()
    ).all()
    for name in lead_cities:
        clean = str(name or "").strip()
        key = (clean.casefold(), "GO")
        if clean and key not in existing_names:
            city = City(name=clean, state="GO")
            db.add(city)
            db.flush()
            existing_names[key] = city
            changed = True
    if not existing_names:
        city = City(name="Cidade principal", state="GO")
        db.add(city)
        db.flush()
        existing_names[(city.name.casefold(), city.state)] = city
        changed = True
    for lead in db.scalars(select(Lead).where(Lead.city_id.is_(None), Lead.city.is_not(None))).all():
        city = existing_names.get((str(lead.city).strip().casefold(), "GO"))
        if city:
            lead.city_id = city.id
            changed = True
    if changed:
        db.commit()


def seed_demo(db) -> None:
    if db.scalar(select(func.count(Segment.id))):
        return
    city = db.scalar(select(City).where(City.name == "Alto Horizonte", City.state == "GO"))
    if not city:
        city = City(name="Alto Horizonte", state="GO")
        db.add(city)
        db.flush()
    segments = [
        Segment(name="Donos de cachorros", description="Identificados por respostas sobre cães.", kind="smart", color="#2563eb", keywords_json=json.dumps(["cachorro", "cao", "cadela", "canino", "pitbull", "labrador", "vira lata", "pinscher"], ensure_ascii=False), min_confidence=0.72),
        Segment(name="Donos de gatos", description="Identificados por respostas sobre gatos.", kind="smart", color="#7c3aed", keywords_json=json.dumps(["gato", "gata", "felino", "siames", "persa"], ensure_ascii=False), min_confidence=0.72),
        Segment(name="Promotores", description="Notas altas de satisfação.", kind="automatic", color="#16a34a"),
        Segment(name="Detratores", description="Notas baixas que exigem atenção.", kind="automatic", color="#dc2626"),
        Segment(name="Interessados em vacinação", description="Interesse detectado em respostas abertas.", kind="smart", color="#f59e0b", keywords_json=json.dumps(["vacina", "vacinacao", "antirrabica", "carteira de vacina"], ensure_ascii=False), min_confidence=0.70),
    ]
    db.add_all(segments)
    db.flush()
    by_name = {item.name: item for item in segments}

    onboarding = Questionnaire(
        name="Cadastro inicial pelo WhatsApp",
        description="Fluxo curto para novos contatos que chegam diretamente pelo WhatsApp.",
        objective="registration",
        status="active",
        channels_json='["whatsapp"]',
        response_mode="identified",
        trigger_type="whatsapp_onboarding",
        opening_message="Olá! Para participar das pesquisas, vou fazer um cadastro bem rápido.",
        closing_message="Cadastro concluído. Quando houver uma pesquisa adequada, falaremos por aqui.",
        alert_enabled=False,
    )
    onboarding.questions = [
        Question(position=1, text="Como podemos chamar você?", type="text", required=True),
        Question(position=2, text="Você possui qual tipo de animal?", type="choice", whatsapp_response_mode="option_list", options_json=json.dumps([
            {"id": "dog", "label": "Cachorro", "value": "cachorro", "segment_id": by_name["Donos de cachorros"].id},
            {"id": "cat", "label": "Gato", "value": "gato", "segment_id": by_name["Donos de gatos"].id},
            {"id": "both", "label": "Ambos", "value": "cachorro e gato", "segment_ids": [by_name["Donos de cachorros"].id, by_name["Donos de gatos"].id]},
            {"id": "other", "label": "Outro", "value": "outro"},
        ], ensure_ascii=False)),
    ]
    db.add(onboarding)

    satisfaction = Questionnaire(
        name="Satisfação após o cadastro",
        description="Pesquisa enviada dois dias após o cadastro e repetida a cada 90 dias.",
        objective="satisfaction",
        status="active",
        channels_json='["whatsapp","kiosk","interviewer"]',
        response_mode="identified",
        trigger_type="after_registration",
        delay_value=2,
        delay_unit="days",
        recurrence_days=90,
        opening_message="Olá, {{nome}}! Sua opinião ajuda a melhorar nosso atendimento.",
        closing_message="Obrigado! Sua resposta foi registrada.",
        alert_enabled=True,
        alert_threshold=6,
        alert_severity="high",
        auto_segment=True,
    )
    satisfaction.questions = [
        Question(position=1, text="De 0 a 10, qual a sua satisfação geral?", type="score", min_score=0, max_score=10, low_score_threshold=6, segment_low_id=by_name["Detratores"].id, segment_high_id=by_name["Promotores"].id),
        Question(position=2, text="O que mais influenciou sua nota?", type="choice", whatsapp_response_mode="option_list", options_json=json.dumps([
            {"id": "service", "label": "Atendimento", "value": "atendimento"},
            {"id": "waiting", "label": "Espera", "value": "tempo de espera", "creates_alert": True},
            {"id": "structure", "label": "Estrutura", "value": "estrutura"},
            {"id": "other", "label": "Outro", "value": "outro"},
        ], ensure_ascii=False)),
        Question(position=3, text="Conte em poucas palavras como podemos melhorar.", type="text", required=False),
    ]
    db.add(satisfaction)

    anonymous = Questionnaire(
        name="Avaliação anônima no ponto de coleta",
        description="Pesquisa sem vínculo com nome ou telefone para quiosque e entrevistador.",
        objective="satisfaction",
        status="active",
        channels_json='["kiosk","interviewer"]',
        response_mode="anonymous",
        trigger_type="manual",
        opening_message="Sua resposta é anônima e será analisada apenas de forma agrupada.",
        closing_message="Obrigado. Sua resposta anônima foi registrada.",
        alert_enabled=True,
        alert_threshold=5,
        alert_severity="high",
        auto_segment=False,
    )
    anonymous.questions = [
        Question(position=1, text="De 0 a 10, como você avalia o atendimento de hoje?", type="score", min_score=0, max_score=10, low_score_threshold=5),
        Question(position=2, text="Como foi o tempo de espera?", type="choice", whatsapp_response_mode="buttons", options_json=json.dumps([
            {"id": "fast", "label": "Rápido", "value": "rápido"},
            {"id": "ok", "label": "Aceitável", "value": "aceitável"},
            {"id": "slow", "label": "Demorado", "value": "demorado", "creates_alert": True},
        ], ensure_ascii=False)),
        Question(position=3, text="Deixe uma sugestão, se desejar.", type="text", required=False),
    ]
    db.add(anonymous)

    profile = Questionnaire(
        name="Perfil e interesses",
        description="Questionário opcional para segmentação inteligente.",
        objective="profile",
        status="active",
        channels_json='["kiosk","interviewer","whatsapp"]',
        response_mode="identified",
        trigger_type="manual",
        opening_message="Queremos conhecer melhor seu perfil.",
        closing_message="Perfeito. Usaremos suas respostas para enviar conteúdos mais relevantes.",
        alert_enabled=False,
    )
    profile.questions = [
        Question(position=1, text="Quais animais fazem parte da sua família?", type="text", required=True),
        Question(position=2, text="Qual tema mais interessa agora?", type="choice", whatsapp_response_mode="option_list", options_json=json.dumps([
            {"id": "vaccination", "label": "Vacinação", "value": "vacinação", "segment_id": by_name["Interessados em vacinação"].id},
            {"id": "castration", "label": "Castração", "value": "castração"},
            {"id": "adoption", "label": "Adoção", "value": "adoção"},
            {"id": "care", "label": "Cuidados", "value": "cuidados"},
        ], ensure_ascii=False)),
    ]
    db.add(profile)
    db.flush()

    entry_flow = EntryFlow(
        name="Cadastro completo e avaliação",
        description="Coleta nome, vários pets e o motivo de cada atendimento; confirma o WhatsApp e inicia a satisfação.",
        status="active",
        profiles_json='["kiosk","interviewer"]',
        welcome_title="Conte sobre você e seus pets",
        welcome_text="O cadastro leva poucos minutos. Ao final, enviaremos uma confirmação para seu WhatsApp.",
        phone_verification_mode="send_continue",
        immediate_questionnaire_id=satisfaction.id,
        immediate_channel="screen_identified",
        confirmed_questionnaire_id=None,
        confirmed_channel="none",
        followup_questionnaire_id=profile.id,
        followup_delay_value=7,
        followup_delay_unit="days",
        followup_requires_confirmation=True,
    )
    db.add(entry_flow)
    db.flush()

    demo_lead = Lead(name="Marina Costa", phone="(62) 99999-0001", phone_normalized=normalize_phone("62999990001"), source="kiosk", city="Alto Horizonte", city_id=city.id, neighborhood="Centro", consent_research=True, consent_marketing=True)
    demo_lead.pets = [Pet(name="Thor", species="Cachorro", breed="Vira-lata")]
    db.add(demo_lead)
    db.add(Device(name="Totem principal", city_id=city.id, token=secrets.token_urlsafe(24), mode="kiosk", allow_anonymous=True, default_questionnaire_id=profile.id, default_entry_flow_id=entry_flow.id))
    db.commit()


def seed_entry_flow(db) -> None:
    """Add the 2.2 demonstration flow to databases created by 2.0/2.1."""
    if db.scalar(select(func.count(EntryFlow.id))):
        return
    satisfaction = db.scalar(select(Questionnaire).where(Questionnaire.name == "Satisfação após o cadastro").limit(1))
    followup = db.scalar(select(Questionnaire).where(Questionnaire.name == "Perfil e interesses").limit(1))
    if not satisfaction:
        return
    row = EntryFlow(
        name="Cadastro completo e avaliação",
        description="Coleta nome, vários pets e o motivo de cada atendimento; confirma o WhatsApp e inicia a satisfação.",
        status="active",
        profiles_json='["kiosk","interviewer"]',
        welcome_title="Conte sobre você e seus pets",
        welcome_text="O cadastro leva poucos minutos. Ao final, enviaremos uma confirmação para seu WhatsApp.",
        phone_verification_mode="send_continue",
        immediate_questionnaire_id=satisfaction.id,
        immediate_channel="screen_identified",
        confirmed_channel="none",
        followup_questionnaire_id=followup.id if followup else None,
        followup_delay_value=7,
        followup_delay_unit="days",
        followup_requires_confirmation=True,
    )
    db.add(row)
    db.flush()
    for device in db.scalars(select(Device).where(Device.default_entry_flow_id.is_(None))).all():
        device.default_entry_flow_id = row.id
    db.commit()


def migrate_entry_flow_actions(db) -> None:
    """Transforma a configuração única da 2.2 em ações múltiplas, sem duplicar."""
    changed = False
    for flow in db.scalars(select(EntryFlow)).all():
        if db.scalar(select(func.count(EntryFlowAction.id)).where(EntryFlowAction.flow_id == flow.id)):
            continue
        position = 1
        legacy_actions = [
            (
                flow.immediate_questionnaire_id,
                "Pesquisa imediata",
                "after_registration",
                flow.immediate_channel,
                0,
                "minutes",
                flow.phone_verification_mode == "required",
            ),
            (
                flow.confirmed_questionnaire_id,
                "Após confirmar o WhatsApp",
                "after_confirmation",
                flow.confirmed_channel,
                0,
                "minutes",
                True,
            ),
            (
                flow.followup_questionnaire_id,
                "Acompanhamento",
                "after_registration",
                "whatsapp",
                flow.followup_delay_value,
                flow.followup_delay_unit,
                flow.followup_requires_confirmation,
            ),
        ]
        for questionnaire_id, name, trigger, channel, delay, unit, confirmation in legacy_actions:
            if not questionnaire_id or not channel or channel == "none":
                continue
            db.add(EntryFlowAction(
                flow_id=flow.id,
                position=position,
                name=name,
                trigger=trigger,
                questionnaire_id=questionnaire_id,
                channel=channel,
                delay_value=delay or 0,
                delay_unit=unit or "minutes",
                require_confirmation=confirmation,
                schedule_mode="day_hour" if unit == "days" and delay else "exact_interval",
            ))
            position += 1
            changed = True
    if changed:
        db.commit()


def ensure_structured_registration_questionnaire(db) -> None:
    """Cria um cadastro mínimo editável e o aplica aos fluxos antigos sem apagar suas opções."""
    key = "structured-registration-v1"
    questionnaire = db.scalar(select(Questionnaire).where(Questionnaire.seed_key == key).limit(1))
    created = False
    if not questionnaire:
        questionnaire = Questionnaire(
            seed_key=key,
            name="Cadastro essencial de responsável e pet",
            description="Cadastro simples usado pelos fluxos de entrada. Novas perguntas sem vínculo podem ser adicionadas como pesquisa complementar.",
            objective="registration",
            status="active",
            channels_json='["kiosk","interviewer"]',
            response_mode="identified",
            trigger_type="manual",
            opening_message="",
            closing_message="Cadastro registrado.",
            alert_enabled=False,
            auto_segment=False,
        )
        questionnaire.questions = [
            Question(position=1, text="Nome completo", type="text", required=True, data_binding="lead.name"),
            Question(position=2, text="WhatsApp", type="text", required=True, help_text="Usado para confirmar o cadastro e enviar pesquisas autorizadas.", data_binding="lead.phone"),
            Question(position=3, text="Cidade", type="text", required=False, data_binding="lead.city"),
            Question(position=4, text="Bairro", type="text", required=False, data_binding="lead.neighborhood"),
            Question(position=5, text="Nome do pet", type="text", required=False, data_binding="pet.name"),
            Question(
                position=6,
                text="Espécie",
                type="choice",
                required=False,
                options_json=json.dumps([
                    {"id": "cao", "label": "Cachorro", "value": "Cachorro"},
                    {"id": "gato", "label": "Gato", "value": "Gato"},
                    {"id": "ave", "label": "Ave", "value": "Ave"},
                    {"id": "outro", "label": "Outro", "value": "Outro"},
                ], ensure_ascii=False),
                data_binding="pet.species",
            ),
            Question(position=7, text="Motivo principal", type="text", required=False, data_binding="visit.reason"),
            Question(position=8, text="Serviço", type="text", required=False, data_binding="visit.service_type"),
        ]
        db.add(questionnaire)
        db.flush()
        created = True
    changed = False
    for flow in db.scalars(select(EntryFlow).where(EntryFlow.registration_questionnaire_id.is_(None))).all():
        flow.registration_questionnaire_id = questionnaire.id
        changed = True
    if changed or created:
        db.commit()


LEGACY_QUESTIONNAIRES = [
    {
        "key": "legacy16-pet-form",
        "name": "Ficha do pet e responsável · catálogo 1.6",
        "description": "Perguntas do cadastro detalhado da versão 1.6, disponíveis para adaptação.",
        "objective": "registration",
        "questions": [
            ("Qual o nome dele/dela?", "text", []),
            ("É gato ou cachorro?", "choice", ["Gato", "Cachorro", "Outro"]),
            ("Quantos aninhos?", "choice", ["Menos de 1", "1–3", "4–7", "8 ou mais", "Não sei"]),
            ("Macho ou fêmea? Castrado?", "choice", ["Macho castrado", "Macho não castrado", "Fêmea castrada", "Fêmea não castrada", "Não sei"]),
            ("Ele é o único lá em casa?", "choice", ["Só ele", "2 pets", "3 pets", "4 ou mais"]),
            ("O que traz vocês aqui hoje?", "text", []),
            ("E o seu nome?", "text", []),
            ("Vocês são aqui do bairro mesmo?", "text", []),
            ("Qual telefone podemos usar no acompanhamento?", "text", []),
            ("Última vacina, se lembrar", "choice", ["Menos de 6 meses", "6 meses a 1 ano", "Mais de 1 ano", "Não lembro", "Nunca"]),
        ],
    },
    {
        "key": "legacy16-structure",
        "name": "Estrutura e acolhimento · catálogo 1.6",
        "description": "Banco de perguntas sobre limpeza, espera, recepção, acesso e conforto.",
        "objective": "satisfaction",
        "response_mode": "anonymous",
        "questions": [
            ("Como está a limpeza do local hoje?", "choice", ["Muito ruim", "Ruim", "Boa", "Muito boa"]),
            ("O espaço de espera é confortável?", "choice", ["Sim", "Mais ou menos", "Não"]),
            ("Você se sentiu bem recebido na chegada?", "choice", ["Sim", "Mais ou menos", "Não"]),
            ("Te informaram quanto tempo ia demorar?", "yes_no", []),
            ("Foi fácil marcar ou chegar até aqui?", "choice", ["Fácil", "Razoável", "Difícil"]),
            ("Seu pet está confortável e seguro aqui na espera?", "choice", ["Sim", "Mais ou menos", "Não"]),
            ("O banheiro estava limpo e disponível?", "choice", ["Sim", "Não", "Não usei"]),
            ("É fácil se localizar aqui dentro?", "choice", ["Sim", "Mais ou menos", "Não"]),
            ("Alguém da sua família tem dificuldade de acesso aqui?", "choice", ["Não", "Um pouco", "Bastante"]),
            ("Tem alguma coisa aqui que a gente poderia melhorar?", "text", []),
        ],
    },
    {
        "key": "legacy16-d2-core",
        "name": "Pesquisa D+2 completa · catálogo 1.6",
        "description": "Resultado do atendimento, recomendação, equipe, espera e resolutividade dois dias depois.",
        "objective": "satisfaction",
        "questions": [
            ("Você trouxe o {{pet_nome}} por causa de {{pet_motivo}}. Resolveu o que você precisava?", "choice", ["Sim", "Em parte", "Não"]),
            ("De 0 a 10, o quanto você indicaria o atendimento para um amigo?", "score", []),
            ("O veterinário te explicou direitinho o que fazer em casa?", "choice", ["Sim", "Mais ou menos", "Não"]),
            ("Você sentiu que trataram bem o seu pet?", "choice", ["Sim", "Mais ou menos", "Não"]),
            ("O tempo total de espera foi…", "choice", ["Rápido", "Aceitável", "Demorado"]),
            ("Conseguiu resolver numa visita só?", "choice", ["Sim", "Tive que voltar"]),
        ],
    },
    {
        "key": "legacy16-d2-low",
        "name": "Complemento D+2 · nota baixa · catálogo 1.6",
        "description": "Pergunta aberta da antiga ramificação para detratores.",
        "objective": "satisfaction",
        "questions": [("Obrigado pela sinceridade. O que aconteceu? Quero levar isso para a equipe.", "text", [])],
    },
    {
        "key": "legacy16-d2-neutral",
        "name": "Complemento D+2 · nota neutra · catálogo 1.6",
        "description": "Pergunta aberta da antiga ramificação para notas 7 e 8.",
        "objective": "satisfaction",
        "questions": [("O que faltou para ser 10?", "text", [])],
    },
    {
        "key": "legacy16-d2-high",
        "name": "Complemento D+2 · nota alta · catálogo 1.6",
        "description": "Pergunta aberta da antiga ramificação para promotores.",
        "objective": "satisfaction",
        "questions": [("Que bom! O que a gente mais acertou?", "text", [])],
    },
    {
        "key": "legacy16-d7",
        "name": "Acompanhamento D+7 · catálogo 1.6",
        "description": "Acompanhamento sobre a evolução do pet após o serviço.",
        "objective": "followup",
        "questions": [("Passando só para saber como o {{pet_nome}} está depois de {{pet_servico}}. Melhorou?", "text", [])],
    },
    {
        "key": "legacy13-quick",
        "name": "Coleta rápida · legado 1.3",
        "description": "Avaliação curta por botões seguida de comentário aberto, como na versão 1.3.",
        "objective": "satisfaction",
        "questions": [
            ("Como você avalia o atendimento de hoje?", "choice", ["Ótimo", "Regular", "Ruim"]),
            ("Quer contar rapidamente o que mais marcou no atendimento?", "text", []),
        ],
    },
    {
        "key": "legacy16-return",
        "name": "Pesquisa de retorno · catálogo 1.6",
        "description": "Comparação com o atendimento anterior e evolução do pet.",
        "objective": "followup",
        "questions": [
            ("Como foi da outra vez, comparando com hoje?", "choice", ["Melhor", "Igual", "Pior"]),
            ("O {{pet_nome}} ficou bom depois de {{pet_servico}}?", "choice", ["Sim", "Teve complicação", "Ainda em tratamento"]),
        ],
    },
]


def _catalog_options(labels: list[str]) -> str:
    alert_values = {"não", "ruim", "muito ruim", "demorado", "difícil", "pior", "teve complicação"}
    return json.dumps(
        [
            {
                "id": f"option_{index}",
                "label": label,
                "value": label.casefold(),
                "creates_alert": label.casefold() in alert_values,
            }
            for index, label in enumerate(labels, start=1)
        ],
        ensure_ascii=False,
    )


def ensure_legacy_questionnaires_and_flow(db) -> None:
    """Install the useful 1.3/1.6 starter content once, without duplicating it."""
    by_key: dict[str, Questionnaire] = {}
    changed = False
    for definition in LEGACY_QUESTIONNAIRES:
        questionnaire = db.scalar(
            select(Questionnaire).where(Questionnaire.seed_key == definition["key"]).limit(1)
        )
        if not questionnaire:
            questionnaire = Questionnaire(
                seed_key=definition["key"],
                name=definition["name"],
                description=definition["description"],
                objective=definition.get("objective", "satisfaction"),
                status="active",
                channels_json='["whatsapp","kiosk","interviewer"]',
                response_mode=definition.get("response_mode", "identified"),
                trigger_type="manual",
                opening_message="Olá, {{primeiro_nome}}! Podemos fazer algumas perguntas rápidas?",
                closing_message="Obrigado! Sua resposta foi registrada.",
                alert_enabled=definition.get("objective") == "satisfaction",
                alert_threshold=6,
                auto_segment=definition.get("objective") == "satisfaction",
            )
            questionnaire.questions = [
                Question(
                    position=position,
                    text=text_value,
                    type=question_type,
                    required=position == 1 or question_type != "text",
                    options_json=_catalog_options(labels),
                    min_score=0,
                    max_score=10,
                    low_score_threshold=6 if question_type == "score" else None,
                    whatsapp_response_mode="buttons" if 0 < len(labels) <= 3 else ("option_list" if labels else "auto"),
                )
                for position, (text_value, question_type, labels) in enumerate(definition["questions"], start=1)
            ]
            db.add(questionnaire)
            db.flush()
            changed = True
        by_key[definition["key"]] = questionnaire

    flow = db.scalar(select(EntryFlow).where(EntryFlow.name == "Coleta rápida · legado 1.3").limit(1))
    if not flow:
        quick = by_key["legacy13-quick"]
        flow = EntryFlow(
            name="Coleta rápida · legado 1.3",
            description="Captura nome e WhatsApp, confirma o número e continua a avaliação curta pelo WhatsApp.",
            status="active",
            profiles_json='["kiosk","interviewer"]',
            welcome_title="Cadastro rápido",
            welcome_text="Informe seu nome e WhatsApp. Depois da confirmação, a avaliação continua por mensagem.",
            allow_existing_lookup=True,
            collect_city=False,
            collect_neighborhood=False,
            allow_no_pet=True,
            max_pets=1,
            phone_verification_mode="required",
            phone_verification_timeout=180,
            allow_manual_confirmation=True,
            closing_title="Confira seu WhatsApp",
            closing_text="Enviamos a confirmação do número. Após confirmar, você receberá duas perguntas rápidas.",
        )
        db.add(flow)
        db.flush()
        db.add(EntryFlowAction(
            flow_id=flow.id,
            position=1,
            name="Avaliação rápida após confirmação",
            trigger="after_confirmation",
            questionnaire_id=quick.id,
            channel="whatsapp",
            delay_value=0,
            delay_unit="minutes",
            schedule_mode="exact_interval",
            require_confirmation=True,
            per_pet=False,
            active=True,
        ))
        changed = True
    if changed:
        db.commit()


def recover_received_callbacks(db) -> int:
    """Recover real Z-API callbacks discarded by the old substring filter bug."""
    from .collection import complete_phone_verification, verification_by_interaction
    from .engine import add_conversation_message, ensure_conversation
    from .media import register_media
    from .zapi import payload_value, received_contact, received_content
    from ..models import ConversationMessage

    rows = db.scalars(
        select(WebhookEvent)
        .where(
            WebhookEvent.event_type == "received",
            WebhookEvent.ignored_reason == "evento_tecnico_ignorado",
        )
        .order_by(WebhookEvent.id)
    ).all()
    recovered = 0
    setting = db.get(SystemSetting, 1)
    for event in rows:
        try:
            payload = json.loads(event.payload_json or "{}")
            event_type = str(payload_value(payload, "type", "event", default="") or "").casefold()
            if event_type != "receivedcallback":
                continue
            contact = received_contact(payload)
            content = received_content(payload)
            phone_raw = contact.get("phone") or str(payload_value(payload, "phone", "from", default="") or "")
            phone = normalize_phone(phone_raw, setting.default_country_code) if phone_raw else None
            lid = contact.get("lid") or None
            if not phone and not lid:
                continue
            lead = db.scalar(
                select(Lead).where((Lead.phone_normalized == phone) if phone else (Lead.whatsapp_lid == lid))
            )
            if not lead and phone and lid:
                lead = db.scalar(select(Lead).where(Lead.whatsapp_lid == lid))
            conversation = ensure_conversation(db, phone, lead, lid)
            external_id = str(payload_value(payload, "messageId", "message_id", "id", "zaapId", default="") or "")[:160] or None
            existing = db.scalar(
                select(ConversationMessage)
                .where(ConversationMessage.external_id == external_id)
                .order_by(ConversationMessage.id.desc())
                .limit(1)
            ) if external_id else None
            text_value = str(content.get("text") or "").strip()
            content_type = str(content.get("content_type") or "text")
            message = existing
            if not message:
                message = add_conversation_message(
                    db,
                    conversation,
                    direction="out" if bool(payload_value(payload, "fromMe", "from_me", default=False)) else "in",
                    content=text_value or f"[{content_type}]",
                    interaction_id=str(content.get("interaction_id") or "").strip() or None,
                    external_id=external_id,
                    reference_external_id=str(content.get("reference_message_id") or "").strip() or None,
                    content_type=content_type,
                )
                db.flush()
                media = content.get("media") if isinstance(content.get("media"), dict) else {}
                if media:
                    register_media(db, media, media_type=content_type, conversation_message_id=message.id)
            if not bool(payload_value(payload, "fromMe", "from_me", default=False)):
                recipient_key = phone or lid or ""
                verification = verification_by_interaction(
                    db,
                    recipient_key,
                    str(content.get("interaction_id") or "").strip() or None,
                    text_value,
                )
                if verification:
                    complete_phone_verification(db, verification)
            event.ignored_reason = None
            event.processed = True
            recovered += 1
        except (ValueError, TypeError, json.JSONDecodeError):
            continue
    if recovered:
        db.commit()
    return recovered
