"""Tests for the allocator arena cap used by the population prepare path."""

from service.infrastructure.stimulation.experimental_gpu import allocator


def test_tuning_applies_once_and_is_idempotent(monkeypatch):
    monkeypatch.setattr(allocator, '_tuned', False)
    monkeypatch.setenv('GENERATOR_ALLOCATOR_TUNING', '1')
    assert allocator.tune() is True
    assert allocator._tuned is True
    assert allocator.tune() is True


def test_tuning_can_be_disabled(monkeypatch):
    monkeypatch.setattr(allocator, '_tuned', False)
    monkeypatch.setenv('GENERATOR_ALLOCATOR_TUNING', '0')
    assert allocator.tune() is False
    assert allocator._tuned is False


def test_release_is_a_no_op_until_tuning_applied(monkeypatch):
    monkeypatch.setattr(allocator, '_tuned', False)
    monkeypatch.setattr(allocator.gc, 'collect', lambda: (_ for _ in ()).throw(AssertionError))
    allocator.release()
