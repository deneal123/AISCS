import pytest

from service.services.simulations.runtime import simulation_queue


def test_queue_defaults_to_existing_simulation_queue(monkeypatch):
    monkeypatch.delenv("SIMULATION_QUEUE", raising=False)
    assert simulation_queue() == "simulation"


def test_queue_can_be_isolated_without_changing_default(monkeypatch):
    monkeypatch.setenv("SIMULATION_QUEUE", "simulation-qa-field")
    assert simulation_queue() == "simulation-qa-field"


@pytest.mark.parametrize("value", ["", "../other", "тест", "x" * 101])
def test_invalid_queue_names_are_rejected(monkeypatch, value):
    monkeypatch.setenv("SIMULATION_QUEUE", value)
    with pytest.raises(RuntimeError):
        simulation_queue()
