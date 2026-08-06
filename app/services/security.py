from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import unicodedata


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    iterations = 260_000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(digest).decode()}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, raw_iterations, raw_salt, raw_digest = password_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.urlsafe_b64decode(raw_salt.encode())
        expected = base64.urlsafe_b64decode(raw_digest.encode())
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(raw_iterations))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def normalize_phone(value: str | None, country_code: str = "55") -> str | None:
    digits = re.sub(r"\D", "", value or "")
    if not digits:
        return None
    digits = digits.removeprefix("00")
    country_code = re.sub(r"\D", "", country_code or "55") or "55"
    if country_code == "55":
        if len(digits) in {10, 11}:
            digits = "55" + digits
        if digits.startswith("55"):
            national = digits[2:]
            # Celulares brasileiros antigos têm DDD + 8 dígitos iniciados por 6–9.
            # A chave canônica sempre usa o nono dígito; fixos (2–5) permanecem intactos.
            if len(national) == 10 and national[:2].isdigit() and national[2:3] in {"6", "7", "8", "9"}:
                digits = "55" + national[:2] + "9" + national[2:]
    elif len(digits) in {10, 11}:
        digits = country_code + digits
    return digits if 12 <= len(digits) <= 15 else None


def phone_variants(value: str | None, country_code: str = "55") -> tuple[str, ...]:
    canonical = normalize_phone(value, country_code)
    if not canonical:
        return ()
    variants = [canonical]
    if canonical.startswith("55") and len(canonical) == 13 and canonical[4] == "9" and canonical[5] in "6789":
        variants.append(canonical[:4] + canonical[5:])
    return tuple(dict.fromkeys(variants))


def normalize_text(value: str | None) -> str:
    raw = unicodedata.normalize("NFKD", value or "")
    raw = "".join(char for char in raw if not unicodedata.combining(char))
    raw = re.sub(r"[^a-zA-Z0-9\s]", " ", raw.lower())
    return re.sub(r"\s+", " ", raw).strip()
