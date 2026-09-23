"""Контракт доставки провайдерских ключей в сайдкар (Фаза 3).

Ключи, заменённые админом в панели, лежат зашифрованными в БД backend'а. После флипа
``AGENTS__ENGINE_MODE=http`` LLM-вызовы делает САЙДКАР, а PG/Redis у него нет по
построению — значит смена ключа до него не доезжала вовсе, и он молча продолжал бить
старым ключом из env. Особенно обидно на ротации мёртвого ключа: админ его заменил,
а ничего не починилось.

Поэтому backend ПУШИТ снимок override'ов в ``POST /providers/keys``. Снимок целиком, а
не дельта: он же используется для восстановления после рестарта сайдкара (тот теряет
override'ы и откатывается к env). ``version`` — счётчик из Redis backend'а; сайдкар
отдаёт применённую версию в ``/health``, по расхождению backend понимает, что нужно
запушить снова.

⚠️ Здесь едут СЕКРЕТЫ. Значения не логируются нигде и не отдаются наружу: ``/health``
показывает только ИМЕНА провайдеров и версию.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ProviderKeysSnapshot(BaseModel):
    """Тело ``POST /providers/keys``: полный набор override'ов + их версия."""

    version: int = Field(default=-1, description="Версия набора ключей (счётчик backend'а)")
    # provider → api_key. Отсутствие провайдера = override снят, берётся ключ из env.
    overrides: dict[str, str] = Field(default_factory=dict)

    model_config = ConfigDict(extra="ignore")

    def provider_names(self) -> list[str]:
        """Имена провайдеров — единственное, что безопасно показывать наружу."""
        return sorted(self.overrides)
