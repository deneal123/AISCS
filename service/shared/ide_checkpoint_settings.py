"""Technical snapshot capacity, not subscription pricing or a billing allowance."""

from typing import Self

from pydantic import BaseModel, Field, model_validator


class IdeCheckpointConfig(BaseModel):
    # Enable only after migration040 and compatible native capture/restore rollout.
    enabled: bool = False
    # A worker-local directory must never acknowledge deletion from another
    # process/container's different filesystem with the same textual root.
    maintenance_local_storage_shared: bool = False
    max_user_bytes: int = Field(default=1024**3, ge=1, lt=2**63)
    max_snapshot_bytes: int = Field(default=64 * 1024**2, ge=1, lt=2**31)
    max_file_bytes: int = Field(default=16 * 1024**2, ge=1, lt=2**31)
    max_total_bytes: int = Field(default=128 * 1024**2, ge=1, lt=2**31)
    manifest_bytes: int = Field(default=4 * 1024**2, ge=1, le=16 * 1024**2)
    entries: int = Field(default=10000, ge=1, le=65533)
    depth: int = Field(default=32, ge=1, le=64)
    max_pending_per_repository: int = Field(default=4, ge=1, le=32)

    @model_validator(mode="after")
    def bounded_policy(self) -> Self:
        if (
            self.max_file_bytes > self.max_total_bytes
            or self.manifest_bytes > self.max_snapshot_bytes
            or self.max_snapshot_bytes > self.max_user_bytes
        ):
            raise ValueError("invalid_ide_checkpoint_capacity")
        return self
