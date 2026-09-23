"""Актуальный официальный тариф GigaChat на 1 февраля 2026 года.

GigaChat API для юридических лиц и ИП тарифицирует суммарные токены
GigaChat Max / GigaChat-2-Max по 0.65 ₽ за 1 000 токенов (с НДС).
Источник: https://developers.sber.ru/docs/ru/gigachat/tariffs/legal-tariffs

Revision ID: 023_gigachat_tariff_2026_02
Revises: 022_user_file_original_name
"""

from alembic import op

revision = "023_gigachat_tariff_2026_02"
down_revision = "022_user_file_original_name"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # У провайдера ставка едина для входа и выхода, поэтому записываем её в оба поля.
    # Обновляем существующие записи намеренно: прежний fallback [0.3, 1.0] не является
    # тарифом GigaChat и даёт неверную стоимость именно для этих model_id.
    op.execute(
        """
        INSERT INTO profile.model_pricing
            (model_id, price_in_rub_per_1k, price_out_rub_per_1k, model_class, updated_by, updated_at)
        VALUES
            ('GigaChat-Max', 0.650000, 0.650000, 'large', 'system:gigachat-tariff-2026-02-01', now()),
            ('GigaChat-2-Max', 0.650000, 0.650000, 'large', 'system:gigachat-tariff-2026-02-01', now())
        ON CONFLICT (model_id) DO UPDATE SET
            price_in_rub_per_1k = EXCLUDED.price_in_rub_per_1k,
            price_out_rub_per_1k = EXCLUDED.price_out_rub_per_1k,
            model_class = EXCLUDED.model_class,
            updated_by = EXCLUDED.updated_by,
            updated_at = now();
        """
    )


def downgrade() -> None:
    # Не возвращаем вымышленный старый fallback: он не был официальным тарифом.
    pass
