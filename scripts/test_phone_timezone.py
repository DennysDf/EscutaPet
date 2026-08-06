from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from app.services.security import normalize_phone, phone_variants
from app.services.timezone import format_local, local_datetime, valid_timezone


assert normalize_phone("556281479264") == "5562981479264"
assert normalize_phone("5562981479264") == "5562981479264"
assert normalize_phone("(62) 8147-9264") == "5562981479264"
assert normalize_phone("(62) 3414-1234") == "556234141234"
assert phone_variants("5562981479264") == ("5562981479264", "556281479264")

utc_value = datetime(2026, 7, 30, 16, 39)
assert format_local(utc_value, "America/Sao_Paulo") == "30/07/2026 13:39"
assert format_local(utc_value, "America/Manaus") == "30/07/2026 12:39"
assert local_datetime(utc_value, "America/Rio_Branco").hour == 11
assert valid_timezone("Fuso/Invalido") == "America/Sao_Paulo"

print("OK - nono dígito brasileiro, variantes e conversão UTC por usuário validados.")
