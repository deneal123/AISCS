import pytest

from service.settings import feedback_cache_bytes


def test_cache_enabled_by_default_and_can_be_disabled(monkeypatch):
    monkeypatch.delenv('GENERATOR_FEEDBACK_CACHE_BYTES', raising=False)
    assert feedback_cache_bytes() == 64 * 1024 * 1024
    monkeypatch.setenv('GENERATOR_FEEDBACK_CACHE_BYTES', '0')
    assert feedback_cache_bytes() == 0


@pytest.mark.parametrize('value', ['-1', '1.5', '１２', '', ' 12'])
def test_invalid_cache_settings_fail_explicitly(monkeypatch, value):
    monkeypatch.setenv('GENERATOR_FEEDBACK_CACHE_BYTES', value)
    with pytest.raises(ValueError, match='GENERATOR_FEEDBACK_CACHE_BYTES'):
        feedback_cache_bytes()
