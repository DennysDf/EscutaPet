from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TIMEZONE = "America/Sao_Paulo"

BRAZIL_TIMEZONES = (
    ("America/Sao_Paulo", "Brasília · São Paulo, Goiás, DF, Sul e Sudeste"),
    ("America/Fortaleza", "Fortaleza · Ceará e parte do Nordeste"),
    ("America/Recife", "Recife · Pernambuco e parte do Nordeste"),
    ("America/Bahia", "Salvador · Bahia"),
    ("America/Belem", "Belém · Pará e Amapá"),
    ("America/Araguaina", "Araguaína · Tocantins"),
    ("America/Maceio", "Maceió · Alagoas e Sergipe"),
    ("America/Santarem", "Santarém · oeste do Pará"),
    ("America/Cuiaba", "Cuiabá · Mato Grosso"),
    ("America/Campo_Grande", "Campo Grande · Mato Grosso do Sul"),
    ("America/Manaus", "Manaus · Amazonas"),
    ("America/Porto_Velho", "Porto Velho · Rondônia"),
    ("America/Boa_Vista", "Boa Vista · Roraima"),
    ("America/Rio_Branco", "Rio Branco · Acre"),
    ("America/Noronha", "Fernando de Noronha"),
)


def valid_timezone(value: str | None, fallback: str = DEFAULT_TIMEZONE) -> str:
    candidate = str(value or "").strip()
    try:
        ZoneInfo(candidate)
        return candidate
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return fallback


def utc_naive(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def local_datetime(value: datetime | None, timezone_name: str | None) -> datetime | None:
    if value is None:
        return None
    source = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    return source.astimezone(ZoneInfo(valid_timezone(timezone_name)))


def format_local(value: datetime | None, timezone_name: str | None, fmt: str = "%d/%m/%Y %H:%M") -> str:
    local = local_datetime(value, timezone_name)
    return local.strftime(fmt) if local else "—"
