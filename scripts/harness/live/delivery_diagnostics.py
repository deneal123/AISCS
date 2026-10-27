"""Закрытые причины отказа доставки: без payload, exception text и capabilities."""

_CODES = frozenset(
    {
        "model_routing_failed",
        "job_service_unavailable",
        "job_creation_failed",
        "job_enqueue_failed",
        "job_execution_failed",
        "job_orchestration_failed",
        "chat_service_error",
    }
)
_STATES = frozenset({"error", "cancelled", "waiting", "blocked", "partial"})


def delivery_diagnostic(result):
    if type(result) is not dict:
        return {"stage": "worker_delivery", "delivery_status": "invalid_result"}
    if result.get("status") == "success":
        return None
    state, code, status = result.get("status"), result.get("error_code"), result.get("status_code")
    return {
        "stage": "worker_delivery",
        "delivery_status": state if type(state) is str and state in _STATES else "other",
        "error_code": code if type(code) is str and code in _CODES else "other",
        "http_status": status if type(status) is int and 100 <= status <= 599 else None,
    }
