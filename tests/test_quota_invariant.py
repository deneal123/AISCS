"""Инвариант «одна активная квота» (аудит T1.2).

Поведение доказано живым прогоном на реальной БД (см. отчёт аудита). Здесь — дешёвый
source-level guard: если кто-то откатит SQL к «читаем одну строку, списываем со всех»,
тест покраснеет. Юнит-тесты биллинга на моках (FakeConnector) SQL не исполняют, поэтому
поведенческую часть на реальной БД проверяем отдельно.

Напоминание про сам баг: остаток читался по ОДНОЙ (newest) активной строке, а списание
UPDATE'ом било по ВСЕМ активным — после перехода через 1-е число у платника free-строка
вставала рядом с продлённой платной, и платник жёг бесплатный пакет даром + терял доступ
к оплаченному балансу.
"""

from pathlib import Path

from service.services.billing.persistence import billing_repository as br


def test_provision_only_when_no_active_quota() -> None:
    """Provision не должен плодить строку при активной квоте (инвариант)."""
    sql = " ".join(br._PROVISION_QUOTA_SQL.split())
    assert "NOT EXISTS" in sql, "provision снова безусловный — вернётся вторая активная строка"
    assert "period_start <= CURRENT_DATE" in sql and "period_end > CURRENT_DATE" in sql


def test_deduct_targets_single_read_row() -> None:
    """Списание бьёт по ОДНОЙ строке (той, что читал remaining), а не по всем активным."""
    sql = " ".join(br._DEDUCT_SUBSCRIPTION_SQL.split())
    assert "ORDER BY period_start DESC LIMIT 1" in sql, "deduct снова без LIMIT — списывает со всех"
    assert "WHERE id = (" in sql, "deduct должен таргетить конкретный id прочитанной строки"


def test_read_and_deduct_use_same_row_ordering() -> None:
    """Чтение и списание согласованы: обе берут newest активную (ORDER BY period_start DESC)."""
    read = " ".join(br._ACTIVE_REMAINING_SQL.split())
    deduct = " ".join(br._DEDUCT_SUBSCRIPTION_SQL.split())
    assert "ORDER BY period_start DESC LIMIT 1" in read
    assert "ORDER BY period_start DESC LIMIT 1" in deduct


def test_merge_migration_exists() -> None:
    """Миграция слияния существующих overlap'ов на месте."""
    versions = Path(__file__).resolve().parents[1] / "alembic" / "versions"
    mig = versions / "021_merge_active_quotas.py"
    assert mig.exists(), "миграция 021_merge_active_quotas отсутствует"
    src = mig.read_text(encoding="utf-8")
    assert 'down_revision = "020_notifications"' in src
    assert "HAVING COUNT(*) > 1" in src, "миграция должна сливать именно overlap'ы (>1 активной)"
