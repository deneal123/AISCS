from __future__ import annotations

import hashlib
import hmac
import secrets

# Границы длины OTP (защита от абсурдных значений из overlay).
_MIN_LEN = 4
_MAX_LEN = 12


def generate_numeric_code(length: int) -> str:
    """Криптостойкий числовой код фиксированной длины (с ведущими нулями)."""
    length = max(_MIN_LEN, min(int(length or _MIN_LEN), _MAX_LEN))
    return "".join(str(secrets.randbelow(10)) for _ in range(length))


def hash_code(code: str, secret: str) -> str:
    """Хеш кода для хранения в Redis (плейнтекст кода не храним)."""
    return hashlib.sha256(f"{code}:{secret}".encode()).hexdigest()


def codes_match(code: str, secret: str, expected_hash: str) -> bool:
    """Constant-time сверка введённого кода с сохранённым хешем."""
    return hmac.compare_digest(hash_code(code, secret), expected_hash or "")
