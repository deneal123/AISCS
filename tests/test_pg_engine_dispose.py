"""PgConnector должен диспозить пул старого движка при смене event loop (аудит T3.1).

Воркер celery делает loop-per-task; без dispose осиротевший пул держал TCP-коннекты к
Postgres до GC/таймаута (замер: +7 коннектов на 40 задач; с фиксом +2). Поведение
проверено живым замером pg_stat_activity; здесь — source-guard от отката.
"""

import inspect

from service.infrastructure.database.postgresql import PgConnector


def test_engine_pool_disposed_on_loop_change():
    src = inspect.getsource(PgConnector._get_engine)
    assert "sync_engine.dispose(" in src, (
        "движок старого loop не диспозится — осиротевший пул держит коннекты до GC"
    )
    # close=False обязателен: event loop старого движка мёртв, и close=True пытается
    # ЗАКРЫТЬ каждый asyncpg-коннект синхронно → MissingGreenlet сыпется ERROR'ом (и
    # закрытие всё равно не удаётся). Пул роняется в обоих случаях — GC добирает коннекты.
    assert "close=False" in src, "dispose без close=False снова сыпет MissingGreenlet в лог"
    # dispose должен идти ДО обнуления _engine (иначе диспозить нечего)
    assert src.index("old_engine = PgConnector._engine") < src.index("sync_engine.dispose(")
