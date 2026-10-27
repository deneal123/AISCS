"""Нулевой расход закрытого задания требует положительного доказательства из БД."""

from service.services.chat.infrastructure.chat_worker.execution.job_state import JobStateUnavailable


def verified_without_dispatch(row, payload, grants):
    # Только под блокировкой закрытого владельца task/job: Stop или исчерпанный retry.
    # Отсутствия текущего журнала недостаточно: предыдущие attempts могли платить.
    if (
        row["admission"] is None
        or row["usage_history"]
        or row["settled_credits"] != 0
        or payload.get("_usage_journal_v1") is not None
        or any(grant["state"] != "waived" for grant in grants)
    ):
        raise JobStateUnavailable("Harness usage unavailable")
    return True
