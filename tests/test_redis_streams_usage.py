import re
from pathlib import Path


def _service_py_files():
    base = Path(__file__).resolve().parents[1] / "service"
    return list(base.rglob("*.py"))


# ⚠️ ОДНО ОСОЗНАННОЕ ИСКЛЮЧЕНИЕ. Доставка БИЗНЕС-ДАННЫХ (чат-чанки, события задач) идёт
# ТОЛЬКО Redis Streams: pub/sub теряет сообщение, если подписчика нет в этот момент, и не
# переживает реконнект воркера — для ответа модели потеря = дыра. Этот инвариант держит
# тест ниже, и снимать его нельзя.
#
# Но персональный канал уведомлений (`user_events`) — не доставка данных, а ЭФЕМЕРНЫЙ
# СИГНАЛ «перечитай X из БД». Там потеря при офлайне БЕЗВРЕДНА и даже желательна: гонять
# Streams с consumer-group, PEL и очисткой ради «перезапроси баланс» — это буфер на
# пустом месте. Поэтому pub/sub разрешён РОВНО в этих файлах и нигде больше.
_PUBSUB_ALLOWED = {"user_events.py", "user_events_ws.py"}


def test_no_redis_publish_or_pubsub_usage():
    """Бизнес-данные не ходят через pub/sub — только эфемерные сигналы в allowlist."""
    for p in _service_py_files():
        if p.name in _PUBSUB_ALLOWED:
            continue
        txt = p.read_text(encoding="utf-8", errors="replace")
        # Check for direct Redis client publish calls (not port method calls)
        assert "redis.publish(" not in txt, f"Found redis.publish( usage in {p}"
        assert "_client.publish(" not in txt, f"Found _client.publish( usage in {p}"
        assert "PubSub" not in txt, f"Found PubSub usage in {p}"
        assert re.search(r"\bpubsub\b", txt, re.IGNORECASE) is None, (
            f"Found pubsub reference in {p}"
        )


def test_pubsub_allowlist_has_no_stale_entries():
    """⚠️ Allowlist не должен переживать сами файлы: иначе он тихо разрешает лишнее."""
    base = Path(__file__).resolve().parents[1] / "service"
    existing = {p.name for p in base.rglob("*.py")}
    stale = _PUBSUB_ALLOWED - existing
    assert not stale, f"в allowlist pub/sub есть несуществующие файлы: {stale}"


def test_uses_redis_streams_xadd():
    """Check that Redis Streams (xadd) are used somewhere in service code (expected)."""
    found = False
    for p in _service_py_files():
        # Кодировка ЯВНО, как и в тесте выше: без неё Python берёт локаль системы,
        # и на Windows (cp1251) любой файл с кириллицей в комментарии роняет тест
        # UnicodeDecodeError'ом — то есть набор не гонялся на половине машин.
        if "xadd(" in p.read_text(encoding="utf-8", errors="replace"):
            found = True
            break
    assert found, "No usage of Redis Streams xadd() found in service code"
