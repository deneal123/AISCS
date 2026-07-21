"""Контракт сайдкара opendataloader: то, на что опирается вызывающий.

Только stdlib — сверку гоняет CI, и она не должна тянуть за собой JVM и LibreOffice.
"""

from __future__ import annotations

import os

SERVICE_VERSION = "1.0.0"
SERVICE_NAME = "opendataloader"

# Потолок тела: сюда приходит сырой документ, не base64.
MAX_BODY_BYTES = int(os.environ.get("ODL_MAX_BYTES", str(20 * 1024 * 1024)))

# ⚠️ СУММА ЭТИХ ДВУХ — фактический дедлайн сервера, и она обязана быть меньше
# клиентского таймаута (`agents.opendataloader_timeout_sec`, дефолт 180).
#
# Было: LibreOffice 120 + парсер 300 = 420 при клиентских 180. Причём парсерный таймаут
# существовал только НА БУМАГЕ: `ODL_PARSE_TIMEOUT_SEC` объявлялся, пробрасывался через
# compose — и НЕ ПРИМЕНЯЛСЯ НИ РАЗУ, вызов `opendataloader_pdf.convert` шёл без
# ограничения. JVM могла висеть сколько угодно, пока клиент давно ушёл.
#
# Уменьшение ничего не отнимает: документ, которому нужно больше 180 с, всё равно не
# доезжал до вызывающего — тот уже отвалился по своему таймауту.
LO_TIMEOUT_SEC = int(os.environ.get("ODL_LO_TIMEOUT_SEC", "70"))
PARSE_TIMEOUT_SEC = int(os.environ.get("ODL_PARSE_TIMEOUT_SEC", "95"))

# Ключи успешного ответа `POST /parse`.
RESPONSE_FIELDS = frozenset({"markdown", "engine", "chars", "duration_sec"})

# Машинные коды ошибок.
ERROR_CODES = frozenset(
    {
        "invalid_request",  # 422
        "empty_body",  # 400
        "request_too_large",  # 413
        "unsupported_format",  # 415
        "not_found",  # 404
        "parse_timeout",  # 504
        "parse_failed",  # 500
        "convert_failed",  # 500
        "internal",  # 500
    }
)
