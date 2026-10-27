"""Mandatory public-Save storage limits, separate from billing/credit prices."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CheckpointStorageBudget:
    max_user_bytes: int
    max_checkpoint_bytes: int
    max_pending_per_repository: int

    def __post_init__(self) -> None:
        if (
            any(
                type(value) is not int
                for value in (
                    self.max_user_bytes,
                    self.max_checkpoint_bytes,
                    self.max_pending_per_repository,
                )
            )
            or not 1 <= self.max_checkpoint_bytes <= self.max_user_bytes < 2**63
            or not 1 <= self.max_pending_per_repository <= 32
        ):
            raise ValueError("invalid_checkpoint_storage_budget")
