from __future__ import annotations

from collections import defaultdict

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from .security import normalize_phone


def _canonical(value: str | None, country_code: str) -> str | None:
    return normalize_phone(value, country_code) if value else None


def migrate_phone_identities(db: Session, country_code: str = "55") -> dict[str, int]:
    """Unifica celulares BR com/sem nono dígito sem alterar dados persistentes fora da identidade."""
    tables = set(inspect(db.get_bind()).get_table_names())
    stats = {"leads_merged": 0, "conversations_merged": 0, "phones_updated": 0}

    lead_rows = db.execute(text(
        "SELECT id, phone, phone_normalized, whatsapp_lid, number_validated, consent_research, "
        "consent_marketing, opted_out_at, last_contact_at, whatsapp_display_name, whatsapp_chat_name, "
        "whatsapp_profile_photo_url, whatsapp_about FROM leads WHERE phone_normalized IS NOT NULL"
    )).mappings().all()
    lead_groups: dict[str, list] = defaultdict(list)
    for row in lead_rows:
        canonical = _canonical(row["phone_normalized"], country_code)
        if canonical:
            lead_groups[canonical].append(row)

    lead_children = (
        "pets", "survey_executions", "alerts", "message_queue", "collection_sessions",
        "phone_verifications", "consent_receipts",
    )
    for canonical, rows in lead_groups.items():
        rows.sort(key=lambda row: (
            row["phone_normalized"] != canonical,
            not bool(row["whatsapp_lid"]),
            not bool(row["number_validated"]),
            row["id"],
        ))
        keeper = rows[0]
        keeper_id = keeper["id"]
        if len(rows) > 1:
            for duplicate in rows[1:]:
                duplicate_id = duplicate["id"]
                if not keeper["whatsapp_lid"] and duplicate["whatsapp_lid"]:
                    db.execute(text("UPDATE leads SET whatsapp_lid = NULL WHERE id = :id"), {"id": duplicate_id})
                    db.execute(text("UPDATE leads SET whatsapp_lid = :lid WHERE id = :id"), {"lid": duplicate["whatsapp_lid"], "id": keeper_id})
                db.execute(text(
                    "UPDATE leads SET number_validated = CASE WHEN number_validated OR :validated THEN 1 ELSE 0 END, "
                    "consent_research = CASE WHEN consent_research OR :research THEN 1 ELSE 0 END, "
                    "consent_marketing = CASE WHEN consent_marketing OR :marketing THEN 1 ELSE 0 END, "
                    "last_contact_at = CASE WHEN last_contact_at IS NULL OR "
                    "(:last_contact IS NOT NULL AND last_contact_at < :last_contact) THEN :last_contact ELSE last_contact_at END, "
                    "opted_out_at = COALESCE(opted_out_at, :opted_out), "
                    "whatsapp_display_name = COALESCE(whatsapp_display_name, :display_name), "
                    "whatsapp_chat_name = COALESCE(whatsapp_chat_name, :chat_name), "
                    "whatsapp_profile_photo_url = COALESCE(whatsapp_profile_photo_url, :photo), "
                    "whatsapp_about = COALESCE(whatsapp_about, :about) WHERE id = :id"
                ), {
                    "validated": bool(duplicate["number_validated"]), "research": bool(duplicate["consent_research"]),
                    "marketing": bool(duplicate["consent_marketing"]), "last_contact": duplicate["last_contact_at"],
                    "opted_out": duplicate["opted_out_at"], "display_name": duplicate["whatsapp_display_name"],
                    "chat_name": duplicate["whatsapp_chat_name"], "photo": duplicate["whatsapp_profile_photo_url"],
                    "about": duplicate["whatsapp_about"], "id": keeper_id,
                })
                if "lead_segments" in tables:
                    db.execute(text(
                        "DELETE FROM lead_segments WHERE lead_id = :duplicate AND segment_id IN "
                        "(SELECT segment_id FROM lead_segments WHERE lead_id = :keeper)"
                    ), {"duplicate": duplicate_id, "keeper": keeper_id})
                    db.execute(text("UPDATE lead_segments SET lead_id = :keeper WHERE lead_id = :duplicate"), {"keeper": keeper_id, "duplicate": duplicate_id})
                for table_name in lead_children:
                    if table_name in tables:
                        db.execute(text(f"UPDATE {table_name} SET lead_id = :keeper WHERE lead_id = :duplicate"), {"keeper": keeper_id, "duplicate": duplicate_id})
                if "conversations" in tables:
                    db.execute(text("UPDATE conversations SET lead_id = :keeper WHERE lead_id = :duplicate"), {"keeper": keeper_id, "duplicate": duplicate_id})
                db.execute(text("UPDATE leads SET phone_normalized = NULL WHERE id = :id"), {"id": duplicate_id})
                db.execute(text("DELETE FROM leads WHERE id = :id"), {"id": duplicate_id})
                stats["leads_merged"] += 1
        db.execute(text("UPDATE leads SET phone_normalized = :phone, phone = :phone WHERE id = :id"), {"phone": canonical, "id": keeper_id})
        if keeper["phone_normalized"] != canonical:
            stats["phones_updated"] += 1

    if "conversations" in tables:
        conversation_rows = db.execute(text(
            "SELECT id, identity_key, phone_normalized, whatsapp_lid, lead_id, unread_count, "
            "last_message_at, last_message_preview FROM conversations"
        )).mappings().all()
        conversation_groups: dict[str, list] = defaultdict(list)
        for row in conversation_rows:
            source = row["phone_normalized"] or (row["identity_key"] if str(row["identity_key"] or "").isdigit() else None)
            canonical = _canonical(source, country_code)
            if canonical:
                conversation_groups[canonical].append(row)
        for canonical, rows in conversation_groups.items():
            rows.sort(key=lambda row: (
                row["phone_normalized"] != canonical,
                not bool(row["lead_id"]),
                not bool(row["whatsapp_lid"]),
                row["id"],
            ))
            keeper = rows[0]
            keeper_id = keeper["id"]
            total_unread = sum(int(row["unread_count"] or 0) for row in rows)
            latest = max(rows, key=lambda row: (row["last_message_at"] is not None, row["last_message_at"] or ""))
            for row in rows:
                db.execute(text("UPDATE conversations SET identity_key = :temporary, phone_normalized = NULL WHERE id = :id"), {"temporary": f"merge:{row['id']}", "id": row["id"]})
            for duplicate in rows[1:]:
                db.execute(text("UPDATE conversation_messages SET conversation_id = :keeper WHERE conversation_id = :duplicate"), {"keeper": keeper_id, "duplicate": duplicate["id"]})
                db.execute(text("DELETE FROM conversations WHERE id = :id"), {"id": duplicate["id"]})
                stats["conversations_merged"] += 1
            db.execute(text(
                "UPDATE conversations SET identity_key = :phone, phone_normalized = :phone, "
                "lead_id = COALESCE(lead_id, :lead_id), whatsapp_lid = COALESCE(whatsapp_lid, :lid), "
                "unread_count = :unread, last_message_at = :last_at, last_message_preview = :preview WHERE id = :id"
            ), {
                "phone": canonical, "lead_id": next((row["lead_id"] for row in rows if row["lead_id"]), None),
                "lid": next((row["whatsapp_lid"] for row in rows if row["whatsapp_lid"]), None),
                "unread": total_unread, "last_at": latest["last_message_at"], "preview": latest["last_message_preview"],
                "id": keeper_id,
            })

    for table_name, column_name in (("message_queue", "phone"), ("phone_verifications", "phone")):
        if table_name not in tables:
            continue
        rows = db.execute(text(f"SELECT id, {column_name} AS phone FROM {table_name}")).mappings().all()
        for row in rows:
            canonical = _canonical(row["phone"], country_code)
            if canonical and canonical != row["phone"]:
                db.execute(text(f"UPDATE {table_name} SET {column_name} = :phone WHERE id = :id"), {"phone": canonical, "id": row["id"]})
                stats["phones_updated"] += 1
    if "zapi_config" in tables:
        rows = db.execute(text("SELECT id, device_phone FROM zapi_config WHERE device_phone IS NOT NULL")).mappings().all()
        for row in rows:
            canonical = _canonical(row["device_phone"], country_code)
            if canonical:
                db.execute(text("UPDATE zapi_config SET device_phone = :phone WHERE id = :id"), {"phone": canonical, "id": row["id"]})
    db.commit()
    db.expire_all()
    return stats
