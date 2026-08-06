from __future__ import annotations

import json
from difflib import SequenceMatcher

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import Lead, LeadSegment, Pet, Question, Segment, SegmentEvent, SegmentRule
from .security import normalize_text


def _score(text: str, keyword: str) -> float:
    text_n = normalize_text(text)
    key_n = normalize_text(keyword)
    if not text_n or not key_n:
        return 0.0
    if key_n in text_n:
        return 1.0
    tokens = text_n.split()
    candidates = tokens + [" ".join(tokens[i:i + 2]) for i in range(max(0, len(tokens) - 1))]
    return max([SequenceMatcher(None, candidate, key_n).ratio() for candidate in candidates] or [0.0])


def attach_segment(db: Session, lead_id: int, segment_id: int, *, origin: str, confidence: float, reason: str) -> LeadSegment:
    existing = next(
        (
            item for item in db.new
            if isinstance(item, LeadSegment)
            and item.lead_id == lead_id
            and item.segment_id == segment_id
        ),
        None,
    )
    if not existing:
        existing = db.scalar(select(LeadSegment).where(LeadSegment.lead_id == lead_id, LeadSegment.segment_id == segment_id))
    if existing:
        if confidence > existing.confidence:
            existing.confidence = confidence
            existing.reason = reason
            existing.origin = origin
            db.add(SegmentEvent(segment_id=segment_id, lead_id=lead_id, event_type="updated", origin=origin, confidence=confidence, reason=reason[:360]))
        return existing
    item = LeadSegment(lead_id=lead_id, segment_id=segment_id, origin=origin, confidence=confidence, reason=reason[:360])
    db.add(item)
    db.add(SegmentEvent(segment_id=segment_id, lead_id=lead_id, event_type="entered", origin=origin, confidence=confidence, reason=reason[:360]))
    return item


def detach_segment(db: Session, lead_id: int, segment_id: int, *, origin: str = "rule", reason: str = "Não atende mais às regras.") -> bool:
    existing = db.scalar(select(LeadSegment).where(LeadSegment.lead_id == lead_id, LeadSegment.segment_id == segment_id))
    if not existing:
        return False
    db.add(SegmentEvent(segment_id=segment_id, lead_id=lead_id, event_type="left", origin=origin, confidence=existing.confidence, reason=reason[:360]))
    db.delete(existing)
    return True


def _rule_values(lead: Lead, rule: SegmentRule) -> list[str]:
    if rule.field == "city": return [lead.city or ""]
    if rule.field == "neighborhood": return [lead.neighborhood or ""]
    if rule.field == "source": return [lead.source or ""]
    if rule.field == "name": return [lead.name or ""]
    if rule.field == "pet_species": return [pet.species or "" for pet in lead.pets]
    if rule.field == "pet_breed": return [pet.breed or "" for pet in lead.pets]
    if rule.field == "whatsapp_confirmed": return ["sim" if lead.number_validated else "nao"]
    if rule.field == "consent_research": return ["sim" if lead.consent_research else "nao"]
    return []


def _rule_matches(lead: Lead, rule: SegmentRule) -> bool:
    values = [normalize_text(value) for value in _rule_values(lead, rule)]
    expected = normalize_text(rule.value)
    if rule.operator == "exists": return any(values)
    if rule.operator == "not_exists": return not any(values)
    if rule.operator == "not_equals": return all(value != expected for value in values) if values else True
    if rule.operator == "not_contains": return all(expected not in value for value in values) if values else True
    if rule.operator == "contains": return any(expected in value for value in values)
    return any(value == expected for value in values)


def lead_matches_rules(lead: Lead, rules: list[SegmentRule]) -> bool:
    active = [rule for rule in rules if rule.active]
    if not active:
        return False
    mode = active[0].group_mode if active else "all"
    results = [_rule_matches(lead, rule) for rule in active]
    return any(results) if mode == "any" else all(results)


def refresh_rule_segment(db: Session, segment: Segment) -> dict[str, int]:
    rules = db.scalars(select(SegmentRule).where(SegmentRule.segment_id == segment.id, SegmentRule.active.is_(True)).order_by(SegmentRule.position)).all()
    if not rules:
        return {"entered": 0, "left": 0, "matched": 0}
    leads = db.scalars(select(Lead).where(Lead.source != "laboratory").order_by(Lead.id)).unique().all()
    current_ids = set(db.scalars(select(LeadSegment.lead_id).where(LeadSegment.segment_id == segment.id)).all())
    matched_ids = {lead.id for lead in leads if lead_matches_rules(lead, rules)}
    entered = left = 0
    for lead_id in matched_ids - current_ids:
        attach_segment(db, lead_id, segment.id, origin="compound_rule", confidence=1.0, reason="Atende às regras automáticas do segmento.")
        entered += 1
    for lead_id in current_ids - matched_ids:
        link = db.scalar(select(LeadSegment).where(LeadSegment.lead_id == lead_id, LeadSegment.segment_id == segment.id))
        if link and link.origin == "compound_rule" and detach_segment(db, lead_id, segment.id, origin="compound_rule"):
            left += 1
    return {"entered": entered, "left": left, "matched": len(matched_ids)}


def refresh_all_rule_segments(db: Session) -> dict[str, int]:
    segments = db.scalars(select(Segment).join(SegmentRule).where(Segment.active.is_(True), SegmentRule.active.is_(True)).distinct()).all()
    entered = left = 0
    for segment in segments:
        result = refresh_rule_segment(db, segment)
        entered += result["entered"]; left += result["left"]
    return {"segment_rules_checked": len(segments), "segment_entries": entered, "segment_exits": left}


def segment_from_answer(db: Session, lead_id: int | None, question: Question, answer_text: str, answer_value: str | None = None, numeric_value: float | None = None) -> list[LeadSegment]:
    if not lead_id:
        return []
    attached: list[LeadSegment] = []
    options = json.loads(question.options_json or "[]")
    selected = next((item for item in options if str(item.get("id")) == str(answer_value) or normalize_text(str(item.get("value"))) == normalize_text(answer_text)), None)
    if selected:
        ids = []
        if selected.get("segment_id"):
            ids.append(int(selected["segment_id"]))
        ids.extend(int(value) for value in selected.get("segment_ids", []) if value)
        for segment_id in ids:
            segment = db.get(Segment, segment_id)
            if segment:
                attached.append(attach_segment(db, lead_id, segment_id, origin="question_rule", confidence=1.0, reason=f'Resposta "{answer_text}" em "{question.text}".'))
    if numeric_value is not None:
        if question.segment_low_id and numeric_value <= (question.low_score_threshold if question.low_score_threshold is not None else 6):
            attached.append(attach_segment(db, lead_id, question.segment_low_id, origin="score_rule", confidence=1.0, reason=f"Nota {numeric_value:g} em {question.text}"))
        if question.segment_high_id and numeric_value >= 9:
            attached.append(attach_segment(db, lead_id, question.segment_high_id, origin="score_rule", confidence=1.0, reason=f"Nota {numeric_value:g} em {question.text}"))
    for segment in db.scalars(select(Segment).where(Segment.active.is_(True), Segment.kind == "smart")).all():
        keywords = json.loads(segment.keywords_json or "[]")
        best = max((_score(answer_text, keyword) for keyword in keywords), default=0.0)
        if best >= segment.min_confidence:
            attached.append(attach_segment(db, lead_id, segment.id, origin="semantic_local", confidence=best, reason=f'Similaridade de {best:.0%} entre a resposta "{answer_text[:120]}" e os termos do segmento.'))
    return attached


def segment_from_conversation(
    db: Session,
    lead_id: int | None,
    text: str,
    *,
    origin: str = "conversation_text",
    reason_label: str = "Mensagem recebida no WhatsApp",
) -> list[LeadSegment]:
    """Aplica somente segmentos inteligentes a texto livre auditável."""
    if not lead_id or not normalize_text(text):
        return []
    attached: list[LeadSegment] = []
    for segment in db.scalars(select(Segment).where(Segment.active.is_(True), Segment.kind == "smart")).all():
        keywords = json.loads(segment.keywords_json or "[]")
        best = max((_score(text, keyword) for keyword in keywords), default=0.0)
        if best >= segment.min_confidence:
            attached.append(attach_segment(
                db,
                lead_id,
                segment.id,
                origin=origin,
                confidence=best,
                reason=f'{reason_label}: "{text[:180]}" · similaridade {best:.0%}.',
            ))
    return attached
