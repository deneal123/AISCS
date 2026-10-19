"""Private restore preparation. No public restore API or retention policy here."""

from dataclasses import dataclass, field
from typing import BinaryIO

from infrastructure.ide_bundle_format import BundleFailure, BundleLimits

from application.ide_bundles import IdeBundleService
from application.recovery import RestoreSnapshot, restore_receipt


@dataclass(frozen=True, slots=True)
class IdeRestore:
    source: BinaryIO = field(repr=False)
    snapshot: RestoreSnapshot
    limits: BundleLimits

    async def initialize(self, driver, item, manifest: str) -> None:
        service = IdeBundleService(driver)
        await service.restore(
            item,
            self.source,
            self.limits,
            expected_size=self.snapshot.size,
            expected_sha256=self.snapshot.sha256,
        )
        # Only a confirmed, fully validated restore may get a readiness receipt.
        # A partial or unknown helper result never reaches this commit point.
        if not await service.receipt(item, restore_receipt(manifest), write=True):
            raise BundleFailure("ide_bundle_unavailable")
