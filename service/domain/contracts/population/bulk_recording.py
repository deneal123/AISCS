"""Path-free contract for experimental independent population recording."""

import hashlib
import json
from uuid import UUID

from pydantic import Field

from service.contracts import Contract
from service.domain.contracts.replay import ReplaySimulation


class BulkRecordingConfig(Contract):
    graph_manifest_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    simulation: ReplaySimulation

    def digest(self):
        return hashlib.sha256(json.dumps(self.model_dump(mode='json'),
                                         sort_keys=True, separators=(',', ':'),
                                         allow_nan=False).encode('utf8')).hexdigest()


class BulkRecordingExecutionRequest(Contract):
    execution_id: UUID
    config: BulkRecordingConfig
