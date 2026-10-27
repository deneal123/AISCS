"""The opt-in installed-code runner must reject weak or mismatched evidence."""

import hashlib
import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def smoke(monkeypatch):
    scripts = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location(
        "admin_runtime_smoke_test", scripts / "smoke_admin_runtime.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(
        module, "idle", lambda: {"active": 0, "reserved": 0, "scheduled": 0}
    )
    module.check_configuration = module.configuration_matches
    monkeypatch.setattr(module, "configuration_matches", lambda: None)
    return module


def projection(smoke):
    return {
        "digests": {
            name: hashlib.sha256(
                (smoke.ROOT / "backend" / name).read_bytes()
            ).hexdigest()
            for name in smoke.FILES
        },
        "cases": 8,
        "safe_records": 5,
        "secret_pushes": 0,
        "real_mutations": 0,
    }


@pytest.mark.parametrize("changed", [False, True])
def test_configuration_checks_compose_fields_without_exposing_values(
    smoke, monkeypatch, changed
):
    services = ["backend", "celery-worker-agents", "celery-worker-maintenance"]
    private = "private-configuration-sentinel"

    def decoded(args, stage, **kwargs):
        if stage == "compose_config":
            return {
                "services": {
                    name: {"environment": {"SECRET": private}} for name in services
                }
            }
        return [
            {
                "Config": {
                    "Env": [
                        "SECRET=" + ("changed" if changed else private),
                        "PATH=extra",
                    ]
                }
            }
        ]

    monkeypatch.setattr(smoke, "decoded", decoded)
    if changed:
        with pytest.raises(
            smoke.ProbeFailure, match="configuration_changed"
        ) as failure:
            smoke.check_configuration()
        assert private not in str(failure.value)
    else:
        smoke.check_configuration()


def test_runner_checks_all_three_installed_copies_and_http_health(smoke, monkeypatch):
    calls = []

    def decoded(args, stage, **kwargs):
        calls.append(stage)
        return {"status": 200} if stage == "backend_health" else projection(smoke)

    monkeypatch.setattr(smoke, "decoded", decoded)
    assert smoke.run()["cases"] == 24
    assert calls == ["installed_admin_probe"] * 3 + ["backend_health"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("digests", {}),
        ("cases", 4),
        ("safe_records", 4),
        ("secret_pushes", 1),
        ("real_mutations", 1),
    ],
)
def test_runner_rejects_mismatch_or_mutation(smoke, monkeypatch, field, value):
    result = projection(smoke)
    result[field] = value
    monkeypatch.setattr(smoke, "decoded", lambda *args, **kwargs: result)
    with pytest.raises(smoke.ProbeFailure):
        smoke.run()


@pytest.mark.parametrize("result", [[], None, {"status": 503}])
def test_runner_rejects_malformed_probe(smoke, monkeypatch, result):
    monkeypatch.setattr(smoke, "decoded", lambda *args, **kwargs: result)
    with pytest.raises(smoke.ProbeFailure):
        smoke.run()


@pytest.mark.parametrize("result", [[], None, {"status": 503}])
def test_runner_rejects_unhealthy_http_after_installed_checks(
    smoke, monkeypatch, result
):
    monkeypatch.setattr(
        smoke,
        "decoded",
        lambda args, stage, **kwargs: (
            result if stage == "backend_health" else projection(smoke)
        ),
    )
    with pytest.raises(smoke.ProbeFailure, match="backend_health"):
        smoke.run()
