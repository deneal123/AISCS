"""Redis: единственное внешнее хранилище, к которому сайдкар ходит напрямую."""

from __future__ import annotations

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from ._empty import EmptyStringMeansUnset


class Redis(BaseModel):
    use_ssl: bool = False
    decode_responses: bool = True
    health_check_interval: int = 30


class RedisConfig(EmptyStringMeansUnset, BaseSettings):
    # ⚠️ Префикс обязателен, хотя у backend его исторически нет: без него поля
    # привязываются к ГОЛЫМ именам, и `redis.port` подхватывал `PORT=8090` от uvicorn.
    model_config = SettingsConfigDict(env_prefix="REDIS__")

    enabled: bool = Field(default_factory=bool)
    host: str = Field(default_factory=str)
    port: int = Field(default_factory=int)
    db: int = Field(default_factory=int)
    password: str = Field(default_factory=str)
    session_prefix: str = Field(default_factory=str)
    session_ttl_seconds: int = Field(default_factory=int)
    cache_prefix: str = Field(default_factory=str)
    cache_default_ttl_seconds: int = Field(default_factory=int)
    profile_cache_ttl_seconds: int = Field(default_factory=int)
    settings: Redis = Redis()

    @property
    def dsn(self) -> str:
        auth = f":{self.password}@" if self.password else ""
        scheme = "rediss" if self.settings.use_ssl else "redis"
        return f"{scheme}://{auth}{self.host}:{self.port}/{self.db}"
