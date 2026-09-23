import json
import logging
import time
from typing import Any

from service.infrastructure.agents_client.contracts.events import EventSerializer
from service.infrastructure.messaging import stream_helpers

logger = logging.getLogger(__name__)

# EventSerializer живёт в contracts/events.py (копия потребителя, см. её докстринг;
# Фаза 1). Ре-экспортируем для совместимости: `from ...agent_streaming import
# EventSerializer` продолжает работать. Транспорт (AgentStreamPublisher → Redis)
# остаётся здесь, в backend-инфраструктуре.
__all__ = ["EventSerializer", "AgentStreamPublisher"]


class AgentStreamPublisher:
    def __init__(
        self, redis_client: Any, stream_key: str, retry_attempts: int = 3, retry_delay: float = 0.2
    ) -> None:
        self.redis_client = redis_client
        self.stream_key = stream_key
        self.retry_attempts = retry_attempts
        self.retry_delay = retry_delay
        self.closed = False

    def publish(self, payload: dict[str, Any]) -> bool:
        if self.closed or not self.redis_client:
            return False
        last_error: Exception | None = None
        for attempt in range(1, self.retry_attempts + 1):
            try:
                stream_helpers.xadd_sync(
                    self.redis_client, self.stream_key, {"data": json.dumps(payload)}
                )
                return True
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Failed to publish event to %s (attempt %s/%s)",
                    self.stream_key,
                    attempt,
                    self.retry_attempts,
                )
                if attempt < self.retry_attempts:
                    time.sleep(self.retry_delay)
        if last_error:
            logger.exception(
                "Failed to publish event to stream %s", self.stream_key, exc_info=last_error
            )
        return False

    def close(self) -> None:
        self.closed = True
