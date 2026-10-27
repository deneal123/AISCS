from uuid import uuid4

import pytest
from pydantic import ValidationError

from service.services.jobs.application.dto import StartJobRequest


def test_scientific_job_cannot_bypass_its_configuration_validation_through_legacy_start():
    with pytest.raises(ValidationError, match="scientific configuration"):
        StartJobRequest(file_id=uuid4(), type="SIMULATION")
    assert StartJobRequest(file_id=uuid4(), type="CHAT").type == "CHAT"
