from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class EditorSubmission(Base):
    """Trava persistente contra POSTs repetidos dos editores."""
    __tablename__ = "editor_submissions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    scope: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    destination: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)


class EditorDraft(Base, TimestampMixin):
    """Rascunho separado: nunca altera a entidade publicada nem o worker."""
    __tablename__ = "editor_drafts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    entity_key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    base_revision: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    client_updated_at: Mapped[str | None] = mapped_column(String(50), nullable=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    __table_args__ = (UniqueConstraint("user_id", "entity_type", "entity_key", name="uq_editor_draft_owner_entity"),)


class SystemSetting(Base, TimestampMixin):
    __tablename__ = "system_settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    organization_name: Mapped[str] = mapped_column(String(160), default="Canil Municipal")
    product_name: Mapped[str] = mapped_column(String(100), default="EscutaPet Inteligente")
    timezone_name: Mapped[str] = mapped_column(String(80), default="America/Sao_Paulo")
    default_country_code: Mapped[str] = mapped_column(String(4), default="55")
    quiet_start_hour: Mapped[int] = mapped_column(Integer, default=20)
    quiet_end_hour: Mapped[int] = mapped_column(Integer, default=8)
    contact_cap_days: Mapped[int] = mapped_column(Integer, default=14)
    contact_cap_count: Mapped[int] = mapped_column(Integer, default=3)
    anonymous_minimum: Mapped[int] = mapped_column(Integer, default=7)
    allow_unknown_whatsapp_onboarding: Mapped[bool] = mapped_column(Boolean, default=True)
    primary_color: Mapped[str] = mapped_column(String(16), default="#0f766e")
    secondary_color: Mapped[str] = mapped_column(String(16), default="#2563eb")
    sidebar_color: Mapped[str] = mapped_column(String(16), default="#071a2b")
    footer_text: Mapped[str | None] = mapped_column(String(240), nullable=True)
    logo_horizontal_file: Mapped[str | None] = mapped_column(String(100), nullable=True)
    logo_vertical_file: Mapped[str | None] = mapped_column(String(100), nullable=True)
    logo_icon_file: Mapped[str | None] = mapped_column(String(100), nullable=True)
    branding_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class City(Base, TimestampMixin):
    __tablename__ = "cities"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    state: Mapped[str] = mapped_column(String(2), default="GO", nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    __table_args__ = (UniqueConstraint("name", "state", name="uq_city_name_state"),)


class User(Base, TimestampMixin):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(140), nullable=False)
    username: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(30), default="operator", index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    email: Mapped[str | None] = mapped_column(String(160), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    avatar_color: Mapped[str] = mapped_column(String(16), default="#0f766e")
    preferred_theme: Mapped[str] = mapped_column(String(20), default="system")
    navigation_compact: Mapped[bool] = mapped_column(Boolean, default=False)
    timezone_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    all_cities: Mapped[bool] = mapped_column(Boolean, default=True)
    city_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    chat_signature: Mapped[str | None] = mapped_column(Text, nullable=True)
    chat_signature_enabled: Mapped[bool] = mapped_column(Boolean, default=False)


class Lead(Base, TimestampMixin):
    __tablename__ = "leads"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    phone_normalized: Mapped[str | None] = mapped_column(String(24), unique=True, nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(30), default="manual", index=True)
    status: Mapped[str] = mapped_column(String(24), default="active", index=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    city_id: Mapped[int | None] = mapped_column(ForeignKey("cities.id"), nullable=True, index=True)
    neighborhood: Mapped[str | None] = mapped_column(String(120), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    number_validated: Mapped[bool] = mapped_column(Boolean, default=False)
    consent_research: Mapped[bool] = mapped_column(Boolean, default=False)
    consent_marketing: Mapped[bool] = mapped_column(Boolean, default=False)
    opted_out_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_contact_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    whatsapp_lid: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True, index=True)
    whatsapp_display_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    whatsapp_chat_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    whatsapp_profile_photo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    whatsapp_about: Mapped[str | None] = mapped_column(String(500), nullable=True)
    whatsapp_identity_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    whatsapp_identity_source: Mapped[str | None] = mapped_column(String(40), nullable=True)

    pets: Mapped[list["Pet"]] = relationship(back_populates="lead", cascade="all, delete-orphan")
    collection_sessions: Mapped[list["CollectionSession"]] = relationship(back_populates="lead")
    segment_links: Mapped[list["LeadSegment"]] = relationship(back_populates="lead", cascade="all, delete-orphan")
    city_record: Mapped["City | None"] = relationship()


class Pet(Base, TimestampMixin):
    __tablename__ = "pets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    species: Mapped[str | None] = mapped_column(String(40), nullable=True)
    breed: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sex: Mapped[str | None] = mapped_column(String(20), nullable=True)
    age_range: Mapped[str | None] = mapped_column(String(40), nullable=True)
    lead: Mapped["Lead"] = relationship(back_populates="pets")


class Segment(Base, TimestampMixin):
    __tablename__ = "segments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(300), nullable=True)
    kind: Mapped[str] = mapped_column(String(20), default="manual", index=True)
    color: Mapped[str] = mapped_column(String(16), default="#0f766e")
    keywords_json: Mapped[str] = mapped_column(Text, default="[]")
    min_confidence: Mapped[float] = mapped_column(Float, default=0.82)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    lead_links: Mapped[list["LeadSegment"]] = relationship(back_populates="segment", cascade="all, delete-orphan")


class LeadSegment(Base):
    __tablename__ = "lead_segments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), nullable=False, index=True)
    segment_id: Mapped[int] = mapped_column(ForeignKey("segments.id"), nullable=False, index=True)
    origin: Mapped[str] = mapped_column(String(30), default="manual")
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    reason: Mapped[str | None] = mapped_column(String(360), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    lead: Mapped["Lead"] = relationship(back_populates="segment_links")
    segment: Mapped["Segment"] = relationship(back_populates="lead_links")
    __table_args__ = (UniqueConstraint("lead_id", "segment_id", name="uq_lead_segment"),)


class SegmentEvent(Base):
    """Histórico imutável da entrada, atualização e saída de um público."""
    __tablename__ = "segment_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    segment_id: Mapped[int] = mapped_column(ForeignKey("segments.id"), nullable=False, index=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    origin: Mapped[str] = mapped_column(String(30), default="manual", nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(360), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)
    __table_args__ = (Index("ix_segment_events_period", "segment_id", "occurred_at"),)


class SegmentRule(Base, TimestampMixin):
    __tablename__ = "segment_rules"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    segment_id: Mapped[int] = mapped_column(ForeignKey("segments.id"), nullable=False, index=True)
    position: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    field: Mapped[str] = mapped_column(String(50), nullable=False)
    operator: Mapped[str] = mapped_column(String(30), default="equals", nullable=False)
    value: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    group_mode: Mapped[str] = mapped_column(String(10), default="all", nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    __table_args__ = (Index("ix_segment_rules_segment_position", "segment_id", "position"),)


class SegmentAutomation(Base, TimestampMixin):
    __tablename__ = "segment_automations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    segment_id: Mapped[int] = mapped_column(ForeignKey("segments.id"), nullable=False, index=True)
    # Mantido como questionário principal para compatibilidade com automações 3.5.x.
    questionnaire_id: Mapped[int] = mapped_column(ForeignKey("questionnaires.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    schedule_type: Mapped[str] = mapped_column(String(30), default="once", nullable=False, index=True)
    trigger_type: Mapped[str] = mapped_column(String(30), default="campaign", nullable=False, index=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    recurrence_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    entry_delay_value: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    entry_delay_unit: Mapped[str] = mapped_column(String(20), default="hours", nullable=False)
    selection_strategy: Mapped[str] = mapped_column(String(30), default="single", nullable=False)
    distribution_mode: Mapped[str] = mapped_column(String(20), default="fixed", nullable=False)
    send_window_start: Mapped[int] = mapped_column(Integer, default=540, nullable=False)
    send_window_end: Mapped[int] = mapped_column(Integer, default=1020, nullable=False)
    timezone_name: Mapped[str] = mapped_column(String(80), default="America/Sao_Paulo", nullable=False)
    cooldown_days: Mapped[int] = mapped_column(Integer, default=14, nullable=False)
    max_cycles: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cancel_on_exit: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    block_while_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sample_percent: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    sample_mode: Mapped[str] = mapped_column(String(20), default="per_cycle", nullable=False)
    exclude_previous: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    repeat_policy: Mapped[str] = mapped_column(String(30), default="cooldown", nullable=False)
    require_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False, index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    last_audience_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_created_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    questionnaire: Mapped["Questionnaire"] = relationship()
    segment: Mapped["Segment"] = relationship()
    questionnaires: Mapped[list["SegmentAutomationQuestionnaire"]] = relationship(
        back_populates="automation", cascade="all, delete-orphan", order_by="SegmentAutomationQuestionnaire.position"
    )
    enrollments: Mapped[list["SegmentAutomationEnrollment"]] = relationship(
        back_populates="automation", cascade="all, delete-orphan"
    )
    __table_args__ = (
        Index("ix_segment_automations_due", "status", "next_run_at"),
        Index("ix_segment_automations_trigger", "status", "trigger_type"),
    )


class SegmentAutomationQuestionnaire(Base):
    __tablename__ = "segment_automation_questionnaires"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    automation_id: Mapped[int] = mapped_column(ForeignKey("segment_automations.id", ondelete="CASCADE"), nullable=False, index=True)
    questionnaire_id: Mapped[int] = mapped_column(ForeignKey("questionnaires.id"), nullable=False, index=True)
    position: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    weight: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    automation: Mapped["SegmentAutomation"] = relationship(back_populates="questionnaires")
    questionnaire: Mapped["Questionnaire"] = relationship()
    __table_args__ = (
        UniqueConstraint("automation_id", "questionnaire_id", name="uq_segment_automation_questionnaire"),
        Index("ix_segment_automation_questionnaires_order", "automation_id", "position"),
    )


class SegmentAutomationEnrollment(Base, TimestampMixin):
    """Estado individual do lead dentro de uma automação inteligente de segmento."""
    __tablename__ = "segment_automation_enrollments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    automation_id: Mapped[int] = mapped_column(ForeignKey("segment_automations.id", ondelete="CASCADE"), nullable=False, index=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False, index=True)
    entered_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    next_due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    last_scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_questionnaire_id: Mapped[int | None] = mapped_column(ForeignKey("questionnaires.id"), nullable=True)
    cycle_number: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sent_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    history_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    blocked_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    automation: Mapped["SegmentAutomation"] = relationship(back_populates="enrollments")
    lead: Mapped["Lead"] = relationship()
    last_questionnaire: Mapped["Questionnaire | None"] = relationship()
    __table_args__ = (
        UniqueConstraint("automation_id", "lead_id", name="uq_segment_automation_enrollment"),
        Index("ix_segment_automation_enrollments_due", "status", "next_due_at"),
    )


class Questionnaire(Base, TimestampMixin):
    __tablename__ = "questionnaires"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    seed_key: Mapped[str | None] = mapped_column(String(80), unique=True, nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    objective: Mapped[str] = mapped_column(String(40), default="satisfaction", index=True)
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    channels_json: Mapped[str] = mapped_column(Text, default='["whatsapp"]')
    response_mode: Mapped[str] = mapped_column(String(20), default="identified", index=True)
    trigger_type: Mapped[str] = mapped_column(String(40), default="manual", index=True)
    delay_value: Mapped[int] = mapped_column(Integer, default=0)
    delay_unit: Mapped[str] = mapped_column(String(20), default="days")
    recurrence_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    random_percent: Mapped[int] = mapped_column(Integer, default=100)
    audience_type: Mapped[str] = mapped_column(String(30), default="all")
    target_segment_id: Mapped[int | None] = mapped_column(ForeignKey("segments.id"), nullable=True, index=True)
    opening_message: Mapped[str] = mapped_column(Text, default="Olá, {{nome}}! Podemos fazer algumas perguntas rápidas?")
    closing_message: Mapped[str] = mapped_column(Text, default="Obrigado pela participação!")
    send_hour: Mapped[int] = mapped_column(Integer, default=10)
    max_attempts: Mapped[int] = mapped_column(Integer, default=2)
    retry_hours: Mapped[int] = mapped_column(Integer, default=24)
    stop_after_response: Mapped[bool] = mapped_column(Boolean, default=True)
    alert_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    alert_threshold: Mapped[float] = mapped_column(Float, default=6.0)
    alert_severity: Mapped[str] = mapped_column(String(20), default="high")
    auto_segment: Mapped[bool] = mapped_column(Boolean, default=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    last_edited_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    questions: Mapped[list["Question"]] = relationship(back_populates="questionnaire", cascade="all, delete-orphan", order_by="Question.position")
    target_segment: Mapped["Segment | None"] = relationship()
    versions: Mapped[list["QuestionnaireVersion"]] = relationship(
        back_populates="questionnaire", cascade="all, delete-orphan", order_by="QuestionnaireVersion.version_number"
    )


class QuestionnaireVersion(Base):
    """Publicação imutável usada por execuções e filas.

    O registro vivo em ``questionnaires`` continua sendo o rascunho editável.
    """
    __tablename__ = "questionnaire_versions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    questionnaire_id: Mapped[int] = mapped_column(ForeignKey("questionnaires.id"), nullable=False, index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="published", nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    config_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    content_signature: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    change_summary_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)
    published_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    questionnaire: Mapped["Questionnaire"] = relationship(back_populates="versions")
    questions: Mapped[list["QuestionnaireVersionQuestion"]] = relationship(
        back_populates="version", cascade="all, delete-orphan", order_by="QuestionnaireVersionQuestion.position"
    )
    __table_args__ = (
        UniqueConstraint("questionnaire_id", "version_number", name="uq_questionnaire_version_number"),
    )


class QuestionnaireVersionQuestion(Base):
    __tablename__ = "questionnaire_version_questions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("questionnaire_versions.id"), nullable=False, index=True)
    original_question_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    stable_key: Mapped[str] = mapped_column(String(120), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(String(24), default="choice", nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    help_text: Mapped[str | None] = mapped_column(String(300), nullable=True)
    options_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    min_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_score: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    low_score_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    segment_low_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    segment_high_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    whatsapp_response_mode: Mapped[str] = mapped_column(String(24), default="auto", nullable=False)
    data_binding: Mapped[str | None] = mapped_column(String(60), nullable=True)
    settings_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    version: Mapped["QuestionnaireVersion"] = relationship(back_populates="questions")
    options: Mapped[list["QuestionnaireVersionOption"]] = relationship(
        back_populates="question", cascade="all, delete-orphan", order_by="QuestionnaireVersionOption.position"
    )
    __table_args__ = (
        UniqueConstraint("version_id", "stable_key", name="uq_version_question_stable_key"),
    )


class QuestionnaireVersionOption(Base):
    __tablename__ = "questionnaire_version_options"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_question_id: Mapped[int] = mapped_column(ForeignKey("questionnaire_version_questions.id"), nullable=False, index=True)
    stable_key: Mapped[str] = mapped_column(String(120), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(300), nullable=False)
    value: Mapped[str] = mapped_column(String(300), nullable=False)
    segment_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    creates_alert: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    question: Mapped["QuestionnaireVersionQuestion"] = relationship(back_populates="options")
    __table_args__ = (
        UniqueConstraint("version_question_id", "stable_key", name="uq_version_option_stable_key"),
    )


class QuestionnaireVersionMigrationIssue(Base):
    __tablename__ = "questionnaire_version_migration_issues"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    details: Mapped[str] = mapped_column(Text, nullable=False)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class QuestionnaireVersionMigrationState(Base):
    __tablename__ = "questionnaire_version_migration_state"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    completed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    stats_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)


class Question(Base, TimestampMixin):
    __tablename__ = "questions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    questionnaire_id: Mapped[int] = mapped_column(ForeignKey("questionnaires.id"), nullable=False, index=True)
    position: Mapped[int] = mapped_column(Integer, default=1)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(String(24), default="choice")
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    help_text: Mapped[str | None] = mapped_column(String(300), nullable=True)
    options_json: Mapped[str] = mapped_column(Text, default="[]")
    min_score: Mapped[int] = mapped_column(Integer, default=0)
    max_score: Mapped[int] = mapped_column(Integer, default=10)
    low_score_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    segment_low_id: Mapped[int | None] = mapped_column(ForeignKey("segments.id"), nullable=True)
    segment_high_id: Mapped[int | None] = mapped_column(ForeignKey("segments.id"), nullable=True)
    whatsapp_response_mode: Mapped[str] = mapped_column(String(24), default="auto", nullable=False)
    data_binding: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)
    settings_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    questionnaire: Mapped["Questionnaire"] = relationship(back_populates="questions")


class SurveyExecution(Base, TimestampMixin):
    __tablename__ = "survey_executions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    questionnaire_id: Mapped[int] = mapped_column(ForeignKey("questionnaires.id"), nullable=False, index=True)
    questionnaire_version_id: Mapped[int | None] = mapped_column(ForeignKey("questionnaire_versions.id"), nullable=True, index=True)
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id"), nullable=True, index=True)
    public_token: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    anonymous_token: Mapped[str | None] = mapped_column(String(80), unique=True, nullable=True, index=True)
    channel: Mapped[str] = mapped_column(String(24), default="whatsapp", index=True)
    source: Mapped[str] = mapped_column(String(30), default="automatic")
    status: Mapped[str] = mapped_column(String(24), default="scheduled", index=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    current_position: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_interaction_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_test: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    collection_session_id: Mapped[int | None] = mapped_column(ForeignKey("collection_sessions.id"), nullable=True, index=True)
    flow_action_id: Mapped[int | None] = mapped_column(ForeignKey("entry_flow_actions.id"), nullable=True, index=True)
    pet_id: Mapped[int | None] = mapped_column(ForeignKey("pets.id"), nullable=True, index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(220), unique=True, nullable=True, index=True)
    context_json: Mapped[str] = mapped_column(Text, default="{}")
    invalid_attempts: Mapped[int] = mapped_column(Integer, default=0)
    test_label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    city_id: Mapped[int | None] = mapped_column(ForeignKey("cities.id"), nullable=True, index=True)
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id"), nullable=True, index=True)

    questionnaire: Mapped["Questionnaire"] = relationship()
    questionnaire_version: Mapped["QuestionnaireVersion | None"] = relationship()
    lead: Mapped["Lead | None"] = relationship()
    collection_session: Mapped["CollectionSession | None"] = relationship(back_populates="executions")
    flow_action: Mapped["EntryFlowAction | None"] = relationship()
    pet: Mapped["Pet | None"] = relationship()
    city: Mapped["City | None"] = relationship()
    device: Mapped["Device | None"] = relationship()
    answers: Mapped[list["SurveyAnswer"]] = relationship(back_populates="execution", cascade="all, delete-orphan")

    __table_args__ = (Index("ix_execution_due", "status", "scheduled_at"),)


class SurveyAnswer(Base):
    __tablename__ = "survey_answers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    execution_id: Mapped[int] = mapped_column(ForeignKey("survey_executions.id"), nullable=False, index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), nullable=False, index=True)
    version_question_id: Mapped[int | None] = mapped_column(ForeignKey("questionnaire_version_questions.id"), nullable=True, index=True)
    answer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer_value: Mapped[str | None] = mapped_column(String(180), nullable=True)
    numeric_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    content_type: Mapped[str] = mapped_column(String(30), default="text")
    transcript_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(24), default="web")
    answered_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    execution: Mapped["SurveyExecution"] = relationship(back_populates="answers")
    question: Mapped["Question"] = relationship()
    version_question: Mapped["QuestionnaireVersionQuestion | None"] = relationship()
    __table_args__ = (UniqueConstraint("execution_id", "question_id", name="uq_execution_question"),)


class Alert(Base, TimestampMixin):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    questionnaire_id: Mapped[int | None] = mapped_column(ForeignKey("questionnaires.id"), nullable=True, index=True)
    execution_id: Mapped[int | None] = mapped_column(ForeignKey("survey_executions.id"), nullable=True, index=True)
    answer_id: Mapped[int | None] = mapped_column(ForeignKey("survey_answers.id"), nullable=True)
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(20), default="high", index=True)
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    responsible_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    closing_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    lead: Mapped["Lead | None"] = relationship()
    questionnaire: Mapped["Questionnaire | None"] = relationship()


class Conversation(Base, TimestampMixin):
    __tablename__ = "conversations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    identity_key: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    phone_normalized: Mapped[str | None] = mapped_column(String(24), unique=True, nullable=True, index=True)
    whatsapp_lid: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True, index=True)
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="open")
    unread_count: Mapped[int] = mapped_column(Integer, default=0)
    last_message_preview: Mapped[str | None] = mapped_column(String(240), nullable=True)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    internal_status: Mapped[str] = mapped_column(String(30), default="open", index=True)
    assigned_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    last_read_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lead: Mapped["Lead | None"] = relationship()
    messages: Mapped[list["ConversationMessage"]] = relationship(back_populates="conversation", cascade="all, delete-orphan", order_by="ConversationMessage.occurred_at")


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    content_type: Mapped[str] = mapped_column(String(20), default="text")
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    interaction_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    reference_external_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(24), default="received", index=True)
    status_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    sender_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    reply_to_message_id: Mapped[int | None] = mapped_column(ForeignKey("conversation_messages.id"), nullable=True, index=True)
    quoted_content: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_internal: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    conversation: Mapped["Conversation"] = relationship(back_populates="messages")
    sender_user: Mapped["User | None"] = relationship(foreign_keys=[sender_user_id])
    reply_to: Mapped["ConversationMessage | None"] = relationship(remote_side=[id], foreign_keys=[reply_to_message_id])


class ConversationReaction(Base, TimestampMixin):
    __tablename__ = "conversation_reactions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_message_id: Mapped[int] = mapped_column(ForeignKey("conversation_messages.id"), nullable=False, index=True)
    emoji: Mapped[str] = mapped_column(String(24), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(20), default="contact", nullable=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    external_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    __table_args__ = (UniqueConstraint("conversation_message_id", "emoji", "actor_type", "user_id", name="uq_conversation_reaction_actor"),)


class ConversationDraft(Base, TimestampMixin):
    __tablename__ = "conversation_drafts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    reply_to_message_id: Mapped[int | None] = mapped_column(ForeignKey("conversation_messages.id"), nullable=True)
    __table_args__ = (UniqueConstraint("conversation_id", "user_id", name="uq_conversation_draft_owner"),)


class ConversationNote(Base, TimestampMixin):
    __tablename__ = "conversation_notes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), nullable=False, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)


class TranscriptionConfig(Base, TimestampMixin):
    __tablename__ = "transcription_config"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    transcribe_received: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    transcribe_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    segment_received_text: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    segment_transcripts: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    language: Mapped[str] = mapped_column(String(12), default="pt", nullable=False)
    threads: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    max_duration_seconds: Mapped[int] = mapped_column(Integer, default=600, nullable=False)
    executable_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    ffmpeg_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    last_job_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class TranscriptionJob(Base, TimestampMixin):
    __tablename__ = "transcription_jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    media_asset_id: Mapped[int] = mapped_column(ForeignKey("media_assets.id"), nullable=False, unique=True, index=True)
    conversation_message_id: Mapped[int | None] = mapped_column(ForeignKey("conversation_messages.id"), nullable=True, index=True)
    survey_answer_id: Mapped[int | None] = mapped_column(ForeignKey("survey_answers.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False, index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    worker_token: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    transcript_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    detected_language: Mapped[str | None] = mapped_column(String(20), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    processing_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    __table_args__ = (Index("ix_transcription_jobs_due", "status", "available_at"),)


class MessageQueue(Base, TimestampMixin):
    __tablename__ = "message_queue"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    execution_id: Mapped[int | None] = mapped_column(ForeignKey("survey_executions.id"), nullable=True, index=True)
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id"), nullable=True, index=True)
    question_id: Mapped[int | None] = mapped_column(ForeignKey("questions.id"), nullable=True)
    version_question_id: Mapped[int | None] = mapped_column(ForeignKey("questionnaire_version_questions.id"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(30), default="question")
    phone: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    payload_text: Mapped[str] = mapped_column(Text, nullable=False)
    message_type: Mapped[str] = mapped_column(String(24), default="text", nullable=False)
    buttons_json: Mapped[str] = mapped_column(Text, default="[]")
    media_payload_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    available_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    external_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    conversation_message_id: Mapped[int | None] = mapped_column(ForeignKey("conversation_messages.id"), nullable=True, index=True)
    media_asset_id: Mapped[int | None] = mapped_column(ForeignKey("media_assets.id"), nullable=True, index=True)
    reply_external_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    execution: Mapped["SurveyExecution | None"] = relationship()
    lead: Mapped["Lead | None"] = relationship()
    question: Mapped["Question | None"] = relationship()
    version_question: Mapped["QuestionnaireVersionQuestion | None"] = relationship()
    __table_args__ = (Index("ix_queue_due", "status", "available_at"),)


class Device(Base, TimestampMixin):
    __tablename__ = "devices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    city_id: Mapped[int | None] = mapped_column(ForeignKey("cities.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    token: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    mode: Mapped[str] = mapped_column(String(24), default="kiosk")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_anonymous: Mapped[bool] = mapped_column(Boolean, default=True)
    default_questionnaire_id: Mapped[int | None] = mapped_column(ForeignKey("questionnaires.id"), nullable=True)
    default_entry_flow_id: Mapped[int | None] = mapped_column(ForeignKey("entry_flows.id"), nullable=True)
    hero_title: Mapped[str] = mapped_column(String(180), default="Sua opinião melhora o atendimento")
    hero_text: Mapped[str] = mapped_column(String(360), default="Responda em poucos minutos. Seus dados são protegidos.")
    primary_color: Mapped[str] = mapped_column(String(16), default="#0f766e")
    address: Mapped[str | None] = mapped_column(String(260), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    city: Mapped["City | None"] = relationship()


class EntryFlow(Base, TimestampMixin):
    __tablename__ = "entry_flows"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    last_edited_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    profiles_json: Mapped[str] = mapped_column(Text, default='["kiosk","interviewer"]')
    welcome_title: Mapped[str] = mapped_column(String(180), default="Cadastro e avaliação")
    welcome_text: Mapped[str] = mapped_column(Text, default="Vamos registrar alguns dados e depois ouvir sua opinião.")
    registration_questionnaire_id: Mapped[int | None] = mapped_column(ForeignKey("questionnaires.id"), nullable=True, index=True)
    allow_existing_lookup: Mapped[bool] = mapped_column(Boolean, default=True)
    collect_city: Mapped[bool] = mapped_column(Boolean, default=True)
    collect_neighborhood: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_no_pet: Mapped[bool] = mapped_column(Boolean, default=True)
    max_pets: Mapped[int] = mapped_column(Integer, default=10)
    service_options_json: Mapped[str] = mapped_column(Text, default='["Consulta","Exame","Vacinação","Cirurgia","Castração","Retorno","Medicação","Orientação","Outro"]')
    service_status_options_json: Mapped[str] = mapped_column(Text, default='["Já foi realizado","Está aguardando","Será realizado","Apenas buscando informações"]')
    phone_verification_mode: Mapped[str] = mapped_column(String(30), default="send_continue")
    phone_verification_timeout: Mapped[int] = mapped_column(Integer, default=180)
    allow_manual_confirmation: Mapped[bool] = mapped_column(Boolean, default=True)
    consent_research_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    consent_marketing_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    consent_terms_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    city_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    device_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    consent_terms_version: Mapped[str] = mapped_column(String(40), default="1.0")
    consent_research_text: Mapped[str] = mapped_column(Text, default="Aceito participar de pesquisas relacionadas ao atendimento.")
    consent_marketing_text: Mapped[str] = mapped_column(Text, default="Aceito receber conteúdos e campanhas.")
    immediate_questionnaire_id: Mapped[int | None] = mapped_column(ForeignKey("questionnaires.id"), nullable=True)
    immediate_channel: Mapped[str] = mapped_column(String(30), default="none")
    confirmed_questionnaire_id: Mapped[int | None] = mapped_column(ForeignKey("questionnaires.id"), nullable=True)
    confirmed_channel: Mapped[str] = mapped_column(String(30), default="none")
    followup_questionnaire_id: Mapped[int | None] = mapped_column(ForeignKey("questionnaires.id"), nullable=True)
    followup_delay_value: Mapped[int] = mapped_column(Integer, default=7)
    followup_delay_unit: Mapped[str] = mapped_column(String(20), default="days")
    followup_requires_confirmation: Mapped[bool] = mapped_column(Boolean, default=True)
    closing_title: Mapped[str] = mapped_column(String(180), default="Obrigado!")
    closing_text: Mapped[str] = mapped_column(Text, default="Cadastro concluído com sucesso.")

    immediate_questionnaire: Mapped["Questionnaire | None"] = relationship(foreign_keys=[immediate_questionnaire_id])
    registration_questionnaire: Mapped["Questionnaire | None"] = relationship(foreign_keys=[registration_questionnaire_id])
    confirmed_questionnaire: Mapped["Questionnaire | None"] = relationship(foreign_keys=[confirmed_questionnaire_id])
    followup_questionnaire: Mapped["Questionnaire | None"] = relationship(foreign_keys=[followup_questionnaire_id])
    actions: Mapped[list["EntryFlowAction"]] = relationship(
        back_populates="flow", cascade="all, delete-orphan", order_by="EntryFlowAction.position"
    )
    sessions: Mapped[list["CollectionSession"]] = relationship(back_populates="flow")


class EntryFlowAction(Base, TimestampMixin):
    __tablename__ = "entry_flow_actions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    flow_id: Mapped[int] = mapped_column(ForeignKey("entry_flows.id"), nullable=False, index=True)
    position: Mapped[int] = mapped_column(Integer, default=1)
    name: Mapped[str] = mapped_column(String(160), default="Acompanhamento")
    trigger: Mapped[str] = mapped_column(String(30), default="after_registration", index=True)
    questionnaire_id: Mapped[int] = mapped_column(ForeignKey("questionnaires.id"), nullable=False, index=True)
    version_mode: Mapped[str] = mapped_column(String(30), default="latest_published", nullable=False)
    fixed_version_id: Mapped[int | None] = mapped_column(ForeignKey("questionnaire_versions.id"), nullable=True, index=True)
    channel: Mapped[str] = mapped_column(String(30), default="whatsapp")
    delay_value: Mapped[int] = mapped_column(Integer, default=0)
    delay_unit: Mapped[str] = mapped_column(String(20), default="minutes")
    schedule_mode: Mapped[str] = mapped_column(String(30), default="exact_interval")
    fixed_scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    send_hour: Mapped[int | None] = mapped_column(Integer, nullable=True)
    require_confirmation: Mapped[bool] = mapped_column(Boolean, default=False)
    per_pet: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    depends_on_action_id: Mapped[int | None] = mapped_column(ForeignKey("entry_flow_actions.id"), nullable=True, index=True)
    condition_question_id: Mapped[int | None] = mapped_column(ForeignKey("questions.id"), nullable=True, index=True)
    condition_operator: Mapped[str | None] = mapped_column(String(30), nullable=True)
    condition_value: Mapped[str | None] = mapped_column(String(300), nullable=True)
    conditions_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    condition_logic: Mapped[str] = mapped_column(String(10), default="and", nullable=False)
    random_group: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    random_weight: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    flow: Mapped["EntryFlow"] = relationship(back_populates="actions")
    questionnaire: Mapped["Questionnaire"] = relationship()
    fixed_version: Mapped["QuestionnaireVersion | None"] = relationship()


class CollectionSession(Base, TimestampMixin):
    __tablename__ = "collection_sessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_token: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    flow_id: Mapped[int] = mapped_column(ForeignKey("entry_flows.id"), nullable=False, index=True)
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id"), nullable=True, index=True)
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id"), nullable=True, index=True)
    city_id: Mapped[int | None] = mapped_column(ForeignKey("cities.id"), nullable=True, index=True)
    operator_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    mode: Mapped[str] = mapped_column(String(24), default="kiosk", index=True)
    status: Mapped[str] = mapped_column(String(30), default="started", index=True)
    current_stage: Mapped[str] = mapped_column(String(40), default="registration")
    confirmation_status: Mapped[str] = mapped_column(String(30), default="not_requested")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_test: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    decisions_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)

    flow: Mapped["EntryFlow"] = relationship(back_populates="sessions")
    lead: Mapped["Lead | None"] = relationship(back_populates="collection_sessions")
    device: Mapped["Device | None"] = relationship()
    city: Mapped["City | None"] = relationship()
    pets: Mapped[list["CollectionPet"]] = relationship(back_populates="session", cascade="all, delete-orphan")
    verification: Mapped["PhoneVerification | None"] = relationship(back_populates="session", uselist=False, cascade="all, delete-orphan")
    executions: Mapped[list["SurveyExecution"]] = relationship(back_populates="collection_session")


class CollectionPet(Base, TimestampMixin):
    __tablename__ = "collection_pets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    collection_session_id: Mapped[int] = mapped_column(ForeignKey("collection_sessions.id"), nullable=False, index=True)
    pet_id: Mapped[int] = mapped_column(ForeignKey("pets.id"), nullable=False, index=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    service_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    service_status: Mapped[str | None] = mapped_column(String(100), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    session: Mapped["CollectionSession"] = relationship(back_populates="pets")
    pet: Mapped["Pet"] = relationship()


class PhoneVerification(Base, TimestampMixin):
    __tablename__ = "phone_verifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), nullable=False, index=True)
    collection_session_id: Mapped[int] = mapped_column(ForeignKey("collection_sessions.id"), nullable=False, unique=True, index=True)
    phone: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    token: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    message_queue_id: Mapped[int | None] = mapped_column(ForeignKey("message_queue.id"), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    session: Mapped["CollectionSession"] = relationship(back_populates="verification")
    lead: Mapped["Lead"] = relationship()
    message_queue: Mapped["MessageQueue | None"] = relationship()


class ConsentReceipt(Base):
    __tablename__ = "consent_receipts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), nullable=False, index=True)
    collection_session_id: Mapped[int | None] = mapped_column(ForeignKey("collection_sessions.id"), nullable=True, index=True)
    scope: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    terms_version: Mapped[str] = mapped_column(String(40), nullable=False)
    accepted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    source: Mapped[str] = mapped_column(String(30), default="kiosk")
    accepted_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class ZapiConfig(Base, TimestampMixin):
    __tablename__ = "zapi_config"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    instance_id: Mapped[str | None] = mapped_column(String(180), nullable=True)
    token: Mapped[str | None] = mapped_column(String(220), nullable=True)
    client_token: Mapped[str | None] = mapped_column(String(220), nullable=True)
    send_endpoint_mode: Mapped[str] = mapped_column(String(20), default="automatic")
    manual_send_endpoint: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    use_buttons: Mapped[bool] = mapped_column(Boolean, default=True)
    button_terms_accepted: Mapped[bool] = mapped_column(Boolean, default=False)
    simulate_when_disabled: Mapped[bool] = mapped_column(Boolean, default=True)
    public_base_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    webhook_secret: Mapped[str] = mapped_column(String(100), default="change-me")
    notify_sent_by_me: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_read_message: Mapped[bool] = mapped_column(Boolean, default=False)
    download_received_media: Mapped[bool] = mapped_column(Boolean, default=True)
    max_media_mb: Mapped[int] = mapped_column(Integer, default=50)
    media_retention_days: Mapped[int] = mapped_column(Integer, default=365)
    remote_webhooks_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    connected: Mapped[bool] = mapped_column(Boolean, default=False)
    device_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    device_phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    last_check_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_webhook_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class MediaAsset(Base, TimestampMixin):
    __tablename__ = "media_assets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_message_id: Mapped[int | None] = mapped_column(ForeignKey("conversation_messages.id"), nullable=True, index=True)
    survey_answer_id: Mapped[int | None] = mapped_column(ForeignKey("survey_answers.id"), nullable=True, index=True)
    type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    local_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(160), nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(240), nullable=True)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    download_status: Mapped[str] = mapped_column(String(30), default="not_applicable", index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    transcription_status: Mapped[str] = mapped_column(String(24), default="not_requested", nullable=False, index=True)
    transcript_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript_language: Mapped[str | None] = mapped_column(String(20), nullable=True)
    transcribed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class WorkerState(Base, TimestampMixin):
    __tablename__ = "worker_state"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    status: Mapped[str] = mapped_column(String(30), default="starting")
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    last_cycle_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_stats_json: Mapped[str] = mapped_column(Text, default="{}")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class WebhookEvent(Base):
    __tablename__ = "webhook_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_key: Mapped[str] = mapped_column(String(190), unique=True, nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    processed: Mapped[bool] = mapped_column(Boolean, default=False)
    ignored_reason: Mapped[str | None] = mapped_column(String(160), nullable=True)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    entity: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)
