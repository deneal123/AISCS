"""Declare reproducible upstream entry points, without inventing data or tests."""

import sys
from pathlib import Path

sys.dont_write_bytecode = True
from inventory import REGISTRY, load, save

PY = "/work/env/bin/python"
PIP = "/work/env/bin/pip"
PREFIX = f"python -m venv /work/env; {PIP} install --disable-pip-version-check "
SUFFIX = f"; {PIP} freeze --all > /work/dependencies.lock.txt; {PIP} check"


def py(
    install,
    smoke,
    tests=None,
    functional=None,
    scope="module-import-only",
    admission=512 * 1024**2,
):
    return {
        "image": "python:3.12-slim",
        "admission_bytes": admission,
        "install": PREFIX + install + SUFFIX,
        "native_tests": tests,
        "smoke": smoke,
        "functional": functional,
        "data_scope": scope,
        "native_tests_reason": "No upstream test entry point qualified for this data-free profile",
        "functional_reason": "Registered data and a separately reviewed functional adapter are required",
    }


def main():
    registry = load(REGISTRY)
    profiles = {
        "SIM-001": py(
            '".[test]"',
            PY + " -m fly_arena --help",
            PY
            + " -m pytest -q --capture=sys -o cache_dir=/work/pytest-cache --basetemp=/work/pytest-tmp tests/test_checkpoint.py tests/test_environment.py",
            PY + " /work/probes/fly_arena_probe.py",
            scope="body_demo_without_connectome",
            admission=1024**3,
        ),
        "SIM-002": py(
            "-r requirements.txt brainscale==0.1.0",
            PY + " drosophila_whole_brain_fitting.py --help && " + PY + " /work/probes/fitting_import_probe.py",
            admission=2 * 1024**3,
        ),
        "SIM-005": py(
            "numpy scipy matplotlib torch --index-url https://pypi.org/simple",
            PY + ' -c "import numpy, scipy, torch"',
            functional=PY + " /work/probes/connconstr_probe.py",
            scope="software_fixture_separate_from_author_figure_reproduction",
            admission=2 * 1024**3,
        ),
        "SIM-006": py(
            "numpy scipy pandas pyarrow brian2 torch",
            PY + " main.py --help",
            admission=2 * 1024**3,
        ),
        "SIM-007": py(
            "-r code/confirmatory/requirements-confirmatory.txt",
            PY + ' -c "import numpy, scipy, pandas, pyarrow"',
            PY
            + " code/confirmatory/tests/test_bounds.py; "
            + PY
            + " code/confirmatory/tests/test_confirmatory.py",
            scope="native_synthetic_confirmatory_fixtures",
        ),
        "SIM-009": py(
            "-r backend/requirements.txt pytest",
            PY + ' -c "import numpy, fastapi"',
            "cd backend; " + PY + " -m pytest -q tests/test_core.py",
            scope="mockbrain_backend_not_real_connectome",
            admission=2 * 1024**3,
        ),
        "SIM-012": py(".", PY + ' -c "import fanc"', admission=2 * 1024**3),
        "SIM-014": py(
            "-r requirements.txt",
            PY + ' -c "import brian2, brian2tools"',
            admission=1024**3,
        ),
        "SIM-016": py(
            '".[dev,data]"',
            "/work/env/bin/soup-connectome run --dataset example --device cpu",
            PY + " -m pytest -q",
            PY + " /work/probes/soup_probe.py",
            scope="upstream_four_neuron_design_fixture",
            admission=128 * 1024**2,
        ),
        "SIM-018": py(
            "-r environment/requirements.txt",
            PY + ' -c "import torch, numpy"',
            admission=2 * 1024**3,
        ),
        "SIM-019": py(
            "-r scalebreak_flyvis/requirements.txt pytest",
            PY + ' -c "import flyvis"',
            PY + " -m pytest -q scalebreak_flyvis/tests",
            admission=2 * 1024**3,
        ),
        "SIM-020": py(
            ". pytest",
            PY
            + " -c \"import flygym; from importlib.metadata import version; print(version('flygym'))\"",
            PY + " -m pytest -q tests/core/test_anatomy.py",
            scope="anatomy_not_neural_simulation",
            admission=1024**3,
        ),
        "SIM-021": py(
            ". pytest", PY + ' -c "import flygym_gymnasium"', admission=1024**3
        ),
        "SIM-022": py(
            "-r requirements.txt",
            PY + ' -c "import snntorch, torch"',
            admission=2 * 1024**3,
        ),
        "SIM-024": py(
            "numpy==1.24.4 brian2==2.5.1 pandas joblib pyarrow",
            PY + ' -c "import model; print(model.default_params)"',
            admission=1024**3,
        ),
        "SIM-025": py(".", PY + ' -c "import mbi_paper"', admission=1024**3),
        "SIM-027": py(".", PY + " test_configs.py", admission=2 * 1024**3),
        "SIM-031": py(
            ". pytest",
            PY + ' -c "import flyvis"',
            PY + " -m pytest -q tests/test_initialization.py",
            admission=2 * 1024**3,
        ),
        "SIM-029": {
            "image": "node:22.19.0",
            "admission_bytes": 64 * 1024**2,
            "install": "node --version",
            "install_scope": "no_dependency_native_runner",
            "native_tests": "node tests/run-node.js",
            "smoke": "node --check js/sim-worker.js",
            "functional": "node /work/probes/snedea_worker.cjs",
            "assets": [
                {
                    "source": "SIM-029/assets/connectome.bin.gz",
                    "destination": "connectome.bin.gz",
                    "sha256": "fbf8d440ca1207c7573e1acdd2366f9d0beb9b533c1710f21681264f81b1cc49",
                }
            ],
            "functional_admission_bytes": 192 * 1024**2,
            "data_scope": "legacy_fixture_native_tests_then_real_export_worker_in_Node",
        },
        "SIM-003": {
            "image": "node:22.19.0",
            "admission_bytes": 1024**3,
            "install": "npm ci --cache /work/npm-cache; npm ls --all > /work/dependencies.lock.txt",
            "native_tests": "npm test",
            "smoke": "npm run typecheck",
            "functional": None,
            "functional_reason": "Full terrarium browser scenario requires pinned graph assets",
            "data_scope": "browser_build_and_native_checks",
        },
    }
    reasons = {
        "SIM-004": "MATLAB analysis of larval escape; a licensed MATLAB/validated Octave environment and SCAPE inputs are absent",
        "SIM-008": "Notebook/data release, not a simulator; supplementary tables must be registered before numerical replay",
        "SIM-010": "Julia scientific analysis requires its Julia lock environment and matching optic-lobe datasets",
        "SIM-011": "R BANC analysis depends on a materialisation, data exports and server credentials; it is not an executable fly simulator",
        "SIM-013": "Julia 1.11 ESN experiment requires weight matrices and the author environment, not a body simulator",
        "SIM-015": "Legacy FlyGym API coupling and pretrained LFS weights need resolution before an offline embodied run",
        "SIM-017": "Linux graph-tool and FlyWire v630 data/cluster analyses require a dedicated graph-tool environment",
        "SIM-023": "Native C++ MaleCNS/ViZDoom engine requires a compiled toolchain, pinned game assets and full graph",
        "SIM-026": "CAVE/cloudvolume tutorials require credentials or reachable public routes; preparation utility, not simulator",
        "SIM-030": "Public repository contains sealed results, verify.py, seeds and lock; simulation pipeline explicitly withheld pending publication",
        "SIM-032": "Author pins Python 3.6/PyTorch 1.8/numpy 1.16; a separate legacy image plus worm recordings is required",
        "SIM-033": "Data preparation requires selected dataset exports plus connectome_interpreter dependency; no generic data-free simulator entry point",
    }
    for row in registry["candidates"]:
        if row["id"] in reasons:
            row["evaluation"] = {
                "status": "blocked",
                "reason": reasons[row["id"]],
                "installation": "not_attempted",
                "biological_validation": False,
            }
        elif row["id"] not in profiles:
            raise ValueError("Candidate without a result or profile: " + row["id"])
    # Original Brian2 pins numpy<2, and is explicitly isolated from Python3.12.
    profiles["SIM-024"]["image"] = "python:3.10-slim"
    profiles["SIM-006"]["image"] = "python:3.10-slim"
    profiles["SIM-025"]["image"] = "python:3.11-slim"
    profiles["SIM-001"].update(
        native_tests_admission_bytes=256 * 1024**2,
        smoke_admission_bytes=128 * 1024**2,
        functional_admission_bytes=768 * 1024**2,
        runtime_prefix=(
            "mkdir -p /work/apt-cache/partial /work/apt-lists/partial; "
            "apt-get -o Dir::State::lists=/work/apt-lists update -qq; "
            "apt-get -o Dir::State::lists=/work/apt-lists -o Dir::Cache::archives=/work/apt-cache "
            "install -y --no-install-recommends libegl1 libgl1 libopengl0 libgl1-mesa-dri; "
            "dpkg-query -W > /work/system-packages.txt; "
        ),
    )
    profiles["SIM-022"]["image"] = "python:3.10-slim"
    for sid in [
        "SIM-005",
        "SIM-006",
        "SIM-009",
        "SIM-012",
        "SIM-018",
        "SIM-019",
        "SIM-022",
        "SIM-031",
    ]:
        # Keep CPU installations from pulling several GB of unused CUDA wheels.
        cpu_packages = "torch torchvision" if sid in {"SIM-019", "SIM-031"} else "torch"
        profiles[sid]["install"] = profiles[sid]["install"].replace(
            "python -m venv /work/env;",
            "python -m venv /work/env; "
            + PIP
            + " install "
            + cpu_packages
            + " --index-url https://download.pytorch.org/whl/cpu;",
        )
    save(Path(__file__).with_name("profiles.json"), profiles)
    save(REGISTRY, registry)
    print(len(profiles), "execution profiles;", len(reasons), "explicit prerequisites")


if __name__ == "__main__":
    main()
