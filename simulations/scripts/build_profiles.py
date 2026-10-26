"""Declare reproducible upstream entry points, without inventing data or tests."""

import sys

sys.dont_write_bytecode = True
from inventory import REGISTRY, ROOT, WORK, load, save
from paths import PROFILES

PY = "/work/env/bin/python"
PIP = "/work/env/bin/pip"
PREFIX = f"python -m venv /work/env; {PIP} install --disable-pip-version-check "
SUFFIX = f"; {PIP} freeze --all > /work/dependencies.lock.txt; {PIP} check"
JULIA = (
    "export JULIA_DEPOT_PATH=/work/home/.julia JULIA_NUM_THREADS=4 "
    "JULIA_NUM_PRECOMPILE_TASKS=1 JULIA_PKG_PRECOMPILE_AUTO=0 "
    "DATADEPS_LOAD_PATH=/work/data DATADEPS_ALWAYS_ACCEPT=true; "
)


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
            PY
            + " drosophila_whole_brain_fitting.py --help && "
            + PY
            + " /work/probes/fitting_import_probe.py",
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
            "numpy==1.26.4 scipy pandas pyarrow brian2==2.8.0 torch joblib matplotlib tqdm",
            PY + " main.py --help",
            PY + " /work/probes/eon_probe.py software",
            PY + " /work/probes/eon_probe.py full",
            scope="full_pinned_flywire_v783_pytorch_cpu_separate_software_fixture",
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
        "SIM-008": py(
            "numpy==2.4.4 pandas==3.0.2 pyarrow==25.0.1 requests google-crc32c openpyxl",
            PY + " /work/probes/malecns_notebook_probe.py supplements",
            PY + " /work/probes/malecns_notebook_probe.py software",
            PY + " /work/probes/malecns_notebook_probe.py full",
            scope="notebook_v09_and_separate_pinned_supplemental_tables",
        ),
        "SIM-009": py(
            "-r backend/requirements.txt pytest",
            PY + ' -c "import numpy, fastapi"',
            "cd backend; " + PY + " -m pytest -q tests/test_core.py",
            scope="mockbrain_backend_not_real_connectome",
            admission=2 * 1024**3,
        ),
        "SIM-012": py(
            "--no-compile . pytest",
            PY
            + " -c 'import fanc; from importlib.metadata import version; print(version(\"fanc-fly\"))'",
            PY
            + " -m pytest -q --capture=sys -o cache_dir=/work/pytest-cache --basetemp=/work/pytest-tmp tests/tests.py",
            PY + " /work/probes/fanc_probe.py",
            scope="pinned_authored_swc_render_and_offline_coordinate_fixtures_separate_from_authenticated_FANC_data",
            admission=2 * 1024**3,
        ),
        "SIM-014": py(
            "numpy==1.26.4 -r requirements.txt",
            "cd /work/cache; " + PY + " /work/source/main_single.py --help",
            PY + " /work/probes/flylif_probe.py smoke",
            PY + " /work/probes/flylif_probe.py functional; "
            "ASPA_FLYLIF_EXPORT_DIR=/work/replay-export "
            + PY
            + " /work/probes/flylif_probe.py functional; "
            + PY
            + " /work/probes/flylif_probe.py verify",
            scope="explicit_alternate_FAFB_v783_LIF_response_not_exact_author_graph_or_orientation_map_reproduction",
            admission=1024**3,
        ),
        "SIM-015": py(
            'numpy==1.26.4 "pandas<3" pyarrow scipy joblib matplotlib tqdm brian2==2.8.0 flygym==1.2.0 pygame fpdf2 "setuptools<81"',
            PY
            + " fly_embodied.py --help; "
            + PY
            + " fly_embodied.py --no-viewer --no-brain --duration 0.02",
            PY + " /work/probes/claude_probe.py software",
            PY
            + " /work/probes/claude_probe.py brain-fresh; "
            + PY
            + " /work/probes/claude_embodied.py --fresh",
            scope="pinned_v783_author_fresh_weights_CPU_not_missing_pretrained_checkpoint_reproduction",
            admission=2 * 1024**3,
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
        "SIM-026": py(
            "caveclient==8.2.1 cloud-volume==12.15.2 meshparty==2.0.3 navis==1.12.0 ncollpyde==0.19.0 matplotlib==3.11.2 seaborn==0.13.2 numpy==2.5.4 pandas==2.3.3 scipy==1.18.1 vtk",
            PY + " /work/probes/flyconnectome_probe.py smoke",
            PY + " /work/probes/flyconnectome_probe.py software",
            PY + " -u /work/probes/flyconnectome_probe.py full",
            scope="registered_FlyWire_tutorial_volumes_meshes_annotations_not_simulator",
        ),
        "SIM-027": py(
            "--report /work/install-report.json . 'jax[cpu]==0.6.2' diffrax==0.7.0 "
            "'numpy>=2,<3' pandas matplotlib scipy scikit-learn seaborn pyarrow "
            "'omegaconf>=2.3,<2.4' 'hydra-core>=1.3,<2' 'sparse>=0.17,<0.19' "
            "h5py natsort nvidia-ml-py3 tqdm psutil pyyaml",
            PY + " /work/probes/pugliese_probe.py smoke",
            PY + " /work/probes/pugliese_probe.py software",
            PY + " -u /work/probes/pugliese_probe.py full",
            scope="registered_MANC_T1_rate_network_not_spike_or_ECAP_model",
        ),
        "SIM-031": py(
            ". pytest",
            PY + ' -c "import flyvis"',
            PY + " -m pytest -q tests/test_initialization.py",
            admission=2 * 1024**3,
        ),
        "SIM-032": {
            "image": "python:3.6.15-slim-buster@sha256:d59ee182c4629dd33b240b9bac1a6ff44276e79e66117eba17aed4016845d3b2",
            "environment_storage": "docker-volume",
            "install": "python -m venv /work/env; "
            + PIP
            + " install --disable-pip-version-check pip==21.3.1 setuptools==59.6.0 wheel==0.37.1; "
            + PIP
            + " install --disable-pip-version-check numpy==1.16.4 scipy==1.5.2 pandas==1.1.5 torch==1.8.0+cpu matplotlib==3.3.4 -f https://download.pytorch.org/whl/torch_stable.html; "
            + PIP
            + " freeze --all > /work/dependencies.lock.txt; "
            + PIP
            + " check",
            "native_tests": PY + " /work/probes/wormvae_probe.py software",
            "smoke": PY + " /work/probes/wormvae_probe.py smoke",
            "functional": PY + " -u /work/probes/wormvae_probe.py full",
            "native_tests_reason": "No author suite; own checks call actual loaders, held-out mask and native connectome serialization",
            "functional_reason": "Original current/conductance components on real C.elegans graph, seeds 1/2/3/1 and controls; one native VAE minibatch with exact checkpoint restoration, not paper performance",
            "data_scope": "original_worm_recordings_and_connectome_not_trained_VAE_or_Drosophila",
            "runtime_prefix": PY + " /work/probes/wormvae_prepare.py; ",
        },
        "SIM-033": py(
            "numpy==1.26.4 scipy==1.12.0 pandas==2.2.3 matplotlib==3.9.4 seaborn tqdm",
            PY + " /work/probes/data_prep_probe.py smoke",
            PY + " /work/probes/data_prep_probe.py software",
            PY + " -u /work/probes/data_prep_probe.py full",
            scope="registered_larval_AD_notebook_preparation_no_neural_simulation",
        ),
        "SIM-030": {
            "image": "python:3.11-slim@sha256:b7a9e5f6a93d6d4a31f129bbd4bdee69efccb6ded0fb230d78aafaf37af98377",
            "install": "python -c \"import sys,json; print(sys.version); open('/work/runtime-version.json','w').write(json.dumps({'python':sys.version,'third_party_dependencies':False}))\"",
            "native_tests": "python verify.py",
            "smoke": "python /work/probes/fcta_probe.py inspect",
            "functional": "python /work/probes/fcta_probe.py audit",
            "install_scope": "standard_library_verification_only_not_author_numerical_environment",
            "data_scope": "pinned_sealed_results_and_native_integrity_verifier_not_connectome_runtime",
            "functional_reason": "Audit available bundle; numerical pipeline, raw ensemble and exact original graph inputs are not supplied",
        },
        "SIM-029": {
            "image": "node:22.19.0-slim@sha256:4a4884e8a44826194dff92ba316264f392056cbe243dcc9fd3551e71cea02b90",
            "admission_bytes": 64 * 1024**2,
            "install": "node --version",
            "install_scope": "no_dependency_native_runner",
            "native_tests": "node /work/probes/snedea_native.cjs",
            "smoke": "node --check js/sim-worker.js",
            "functional": "node /work/probes/snedea_full.cjs",
            "data_prepare": "node /work/probes/snedea_prepare.cjs",
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
    profiles["SIM-010"] = {
        "image": "julia:1.11.6-bookworm@sha256:1623eb4161dc20ee57bcf694e48cb16cfc2aed71507e79b2ff170a206ccd7803",
        "environment_dir": "home/.julia",
        "dependency_lock": "dependencies.lock.toml",
        "diagnose_after_native_failure": True,
        "diagnostic_reason": "Keep the native synapse-total failure visible while checking current-data analysis; never waive or rewrite it",
        "runtime_prefix": JULIA,
        "install": JULIA + "mkdir -p /work/home /work/data; "
        "if test -f /work/assets/Manifest.toml; then cp /work/assets/Manifest.toml Manifest.toml; fi; "
        "julia --project=. -e 'import Pkg; Pkg.instantiate(); "
        "Pkg.status(mode=Pkg.PKGMODE_MANIFEST)' ; "
        "cp Manifest.toml /work/dependencies.lock.toml; julia --version > /work/julia-version.txt",
        "native_tests": "julia --project=. test/runtests.jl",
        "smoke": "julia --project=. /work/probes/optic_lobe_probe.jl smoke",
        "functional": "julia --project=. /work/probes/optic_lobe_probe.jl full",
        "data_scope": "real_flywire_v783_princeton_connectivity_analysis_not_dynamic_simulation",
        "admission_bytes": 1024**3,
    }
    julia_lock = next(
        row for row in registry["candidates"] if row["id"] == "SIM-010"
    ).get("environment_lock")
    if julia_lock:
        profiles["SIM-010"]["assets"] = [
            {
                "source": julia_lock["path"].removeprefix(
                    WORK.relative_to(ROOT).as_posix() + "/"
                ),
                "destination": "Manifest.toml",
                "sha256": julia_lock["sha256"],
            }
        ]
    profiles["SIM-011"] = py(
        "numpy==2.0.2 pandas==2.2.3 scipy==1.17.0 matplotlib==3.10.8 pyarrow==25.0.1",
        PY + " /work/probes/banc_probe.py smoke",
        PY + " /work/probes/banc_probe.py software",
        PY + " /work/probes/banc_probe.py full",
        scope="banc_v888_v2_real_graph_native_cascade_kernel_with_explicit_unique_id_adapter",
    )
    profiles["SIM-011"].update(
        image="python:3.12-slim@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704",
        diagnose_after_native_failure=True,
        diagnostic_reason="Retain observed upstream cascade defects; diagnose the real graph with an explicit adapter, without waiving failures",
        native_tests_reason="No upstream unit-test suite; adversarial software checks of the unmodified cascade module",
        r_profile={
            "image": "rocker/r-ver:4.2.1@sha256:6f9339b3e58d872078cb947c2c0089759bb599b99c4f135d7d9ac7569870a808",
            "install": "RGL_USE_NULL=TRUE Rscript /work/probes/banc_r_install.R",
            "native_tests": "RGL_USE_NULL=TRUE Rscript /work/probes/banc_r_check.R",
            "data_scope": "separate_R_4.2.1_minimal_README_environment_and_unmodified_startup",
        },
    )
    profiles["SIM-012"].update(
        image="python:3.12-slim@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704",
        diagnose_after_native_failure=True,
        diagnostic_reason="Unmodified suite includes authenticated service tests and a literal assert 0 == 1; retain its result while checking offline operations separately",
        native_tests_reason="Unmodified tests/tests.py, including the deliberately false placeholder; no authenticated write operations",
    )
    profiles["SIM-013"] = {
        "execution_controller": "conn_esn_linux",
        "image": "julia:1.11.6-bookworm@sha256:1623eb4161dc20ee57bcf694e48cb16cfc2aed71507e79b2ff170a206ccd7803",
        "runtime_environment": "/opt/aspa-julia in disposable retained Linux container; fresh run required after cleanup",
        "dependency_lock": "dependencies.lock.toml",
        "install": "julia --project=. /work/probes/conn_esn_install.jl; julia --version > /work/julia-version.txt",
        "native_tests": "julia --project=. /work/probes/conn_esn_probe.jl native",
        "smoke": "julia --project=. /work/probes/conn_esn_probe.jl smoke",
        "functional": "julia --project=. /work/probes/conn_esn_probe.jl full",
        "native_repl": "julia --project=. /work/probes/conn_esn_native_repl.jl",
        "diagnose_after_native_failure": True,
        "diagnostic_reason": "Keep original script failures visible; diagnose source modules and authored weights separately without rewriting upstream",
        "data_scope": "matched_first_authored_ESN_subnetworks_larva_and_adult_native_memory_task_not_ECAP_or_body",
        "admission_bytes": 1024**3,
    }
    profiles["SIM-014"]["native_tests_reason"] = (
        "No upstream test suite; explicitly authored four-neuron numerical fixture"
    )
    profiles["SIM-014"]["image"] = profiles["SIM-012"]["image"]
    profiles["SIM-014"].pop("functional_reason", None)
    profiles["SIM-014"]["assets"] = [
        {
            "source": "SIM-014/assets/markdown-strings-2.1.1.zip",
            "destination": "markdown-strings-2.1.1.zip",
            "sha256": "79f7e889a652f1efefb62269f76352765bb859a89d34809040761759599360bf",
        }
    ]
    profiles["SIM-014"]["install"] = (
        PREFIX
        + "numpy==1.26.4 setuptools==80.9.0 /work/assets/markdown-strings-2.1.1.zip; "
        + PIP
        + " install --disable-pip-version-check numpy==1.26.4 setuptools==80.9.0 -r requirements.txt"
        + SUFFIX
    )
    profiles["SIM-017"] = {
        "image": "tiagopeixoto/graph-tool@sha256:6998e03f0f47004a580d03ddc3029628631be980b6300c17c1fe937b0286d9fc",
        "environment_storage": "docker-volume",
        "admission_bytes": 1024**3,
        "install": "python -m venv --system-site-packages /work/env; "
        + PIP
        + " install --disable-pip-version-check networkx seaborn tqdm pyintergraph "
        "jupyter-lsp rfc3339-validator rfc3986-validator terminado debugpy nest-asyncio2"
        + SUFFIX,
        "native_tests": PY + " /work/probes/flywire_probe.py software",
        "native_tests_reason": "Own exhaustive motif and graph-helper fixtures; upstream has no native test suite",
        "smoke": PY + " /work/probes/flywire_probe.py inspect",
        "functional": PY + " -u /work/probes/flywire_probe.py full",
        "data_scope": "registered_v630_full_graph_statistics_and_AL_R_structural_controls_not_neural_dynamics",
    }
    profiles["SIM-018"].update(
        image="python:3.12-slim@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704",
        environment_storage="docker-volume",
        install="python -m venv /work/env; "
        + PIP
        + " install --disable-pip-version-check torch torchvision "
        "--index-url https://download.pytorch.org/whl/cpu --report /work/torch-install.json; "
        + PIP
        + " install --disable-pip-version-check -r environment/requirements.txt "
        "flyvis==1.2.0 --report /work/flyvis-install.json" + SUFFIX,
        runtime_prefix="export FLYVIS_ROOT_DIR=/tmp/aspa-flyvis MPLBACKEND=Agg; ",
        native_tests=PY + " /work/probes/control_study_probe.py software",
        native_tests_reason="Own six-node swap fixture; no upstream native test suite",
        smoke=PY
        + " scripts/build_degree_preserving_random_mask.py --help && "
        + PY
        + " scripts/stage3_train_connectome_vs_random_matched_steps_fromscratch.py --help",
        functional=PY
        + " -u /work/probes/control_study_probe.py full && "
        + PY
        + " /work/probes/control_study_plot.py",
        data_scope="visual_full_configured_graph_structural_controls_and_bounded_forward_optimizer_checks",
    )
    profiles["SIM-019"].update(
        image=profiles["SIM-018"]["image"],
        environment_storage="docker-volume",
        install="python -m venv /work/env; "
        + PIP
        + " install --disable-pip-version-check torch torchvision "
        "--index-url https://download.pytorch.org/whl/cpu --report /work/torch-install.json; "
        + PIP
        + " install --disable-pip-version-check -r scalebreak_flyvis/requirements.txt "
        "flyvis==1.2.0 --report /work/study-install.json" + SUFFIX,
        runtime_prefix="export FLYVIS_ROOT_DIR=/tmp/aspa-flyvis WANDB_MODE=disabled MPLBACKEND=Agg; ",
        native_tests=PY + " -m pytest -q --capture=sys -o cache_dir=/work/pytest-cache "
        "--basetemp=/work/pytest-tmp scalebreak_flyvis/tests",
        native_tests_reason="Author-provided tests under scalebreak_flyvis/tests",
        smoke=PY
        + " scalebreak_flyvis/scripts/11_generate_flyvis_native_stimuli.py --help && "
        + PY
        + " scalebreak_flyvis/scripts/12_run_flyvis_pilot_v2.py --help",
        data_scope="native_stimulus_and_analysis_tests_before_pretrained_functional_trial",
        functional=PY + " -u /work/probes/scalebreak_run.py",
    )
    flygym_system = (
        "mkdir -p /work/apt-cache/partial /work/apt-lists/partial; "
        "apt-get -o Dir::State::lists=/work/apt-lists update -qq; "
        "apt-get -o Dir::State::lists=/work/apt-lists -o Dir::Cache::archives=/work/apt-cache "
        "install -y --no-install-recommends libegl1 libgl1 libopengl0 libgl1-mesa-dri; "
        "dpkg-query -W > /work/system-packages.txt; "
    )
    profiles["SIM-020"].update(
        image=profiles["SIM-018"]["image"],
        environment_storage="docker-volume",
        install=flygym_system + PREFIX + ". pytest pytest-cov" + SUFFIX,
        runtime_prefix=flygym_system,
        native_tests=PY + " -m pytest -q --capture=sys -o cache_dir=/work/pytest-cache "
        "--basetemp=/work/pytest-tmp -m 'not warp and not rl and not tutorial and not network' "
        "tests/core/test_anatomy.py tests/core/test_pose.py tests/core/test_physics.py "
        "tests/core/test_compose.py tests/core/test_simulation.py tests/core/test_rendering.py "
        "tests/core/test_vision.py tests/core/test_utils.py tests/core/test_assets.py",
        native_tests_reason="Selected author CPU core and offline asset tests; optional Warp, RL and remote-asset scenarios separate",
        data_scope="pinned_FlyGym_2_1_bundled_NeuroMechFly_CPU_components_not_connectome",
        functional=PY + " /work/probes/flygym2_probe.py",
        functional_reason="CPU body on flat ground; author CPG, seeds 1/2/3/1, reset, adhesion/amplitude/friction controls and video; not a connectome",
    )
    legacy_system = flygym_system.replace(
        "libegl1 libgl1 libopengl0 libgl1-mesa-dri;",
        "libegl1 libgl1 libopengl0 libgl1-mesa-dri libglib2.0-0 ffmpeg;",
    )
    profiles["SIM-021"].update(
        image=profiles["SIM-020"]["image"],
        environment_storage="docker-volume",
        install=legacy_system + PREFIX + ". 'pytest>=8,<9' 'networkx>=3,<4'" + SUFFIX,
        runtime_prefix=legacy_system,
        native_tests=PY + " -m pytest -q --capture=sys -o cache_dir=/work/pytest-cache "
        "--basetemp=/work/pytest-tmp flygym_gymnasium/tests "
        "flygym_gymnasium/examples/locomotion/tests/test_cpg.py "
        "flygym_gymnasium/examples/locomotion/tests/test_hybrid_turning.py",
        native_tests_reason="Author core, Gymnasium, rendering, sensory and selected locomotion tests; optional learning examples separate",
        functional=PY + " /work/probes/flygym_legacy_probe.py",
        functional_reason="Legacy CPU hybrid controller; seeds 1/2/3/1, native reset, asymmetric/zero drives, mixed terrain and decoded video",
        data_scope="pinned_FlyGym_Gymnasium_1_3_2_body_and_author_hybrid_controller_not_connectome",
    )
    profiles["SIM-022"].update(
        image=profiles["SIM-020"]["image"],
        environment_storage="docker-volume",
        install="python -m venv /work/env; "
        + PIP
        + " install --disable-pip-version-check torch==2.14.1+cpu "
        "--index-url https://pypi.org/simple --extra-index-url https://download.pytorch.org/whl/cpu "
        "--report /work/torch-install.json; "
        + PIP
        + " install --disable-pip-version-check -r requirements.txt "
        "--report /work/port-install.json" + SUFFIX,
        native_tests=PY + " /work/probes/snntorch_probe.py software",
        native_tests_reason="No author test suite; own six-node matrix orientation, duplicate-sum and repeated original simulation-function checks",
        smoke=PY + " /work/probes/snntorch_probe.py smoke",
        functional=PY + " /work/probes/snntorch_probe.py full",
        functional_reason="Exact port data; original sparse CPU functions, default 1000-ms sugar runs 1/2/3/1, sensory-ID coverage and discrete spike events",
        data_scope="pinned_FlyWire_v630_sparse_snntorch_port_not_verified_Brian2_equivalence_or_nociception",
    )
    doom_system = (
        "mkdir -p /work/apt-cache/partial /work/apt-lists/partial; "
        "apt-get -o Dir::State::lists=/work/apt-lists update -qq; "
        "apt-get -o Dir::State::lists=/work/apt-lists -o Dir::Cache::archives=/work/apt-cache "
        "install -y --no-install-recommends clang libgomp1 libsdl2-2.0-0 libgl1 libglib2.0-0; "
        "dpkg-query -W > /work/system-packages.txt; "
    )
    profiles["SIM-023"] = {
        "image": "python:3.11-slim@sha256:b7a9e5f6a93d6d4a31f129bbd4bdee69efccb6ded0fb230d78aafaf37af98377",
        "admission_bytes": 2 * 1024**3,
        "environment_storage": "docker-volume",
        "install": doom_system
        + "python -m venv /work/env; "
        + PIP
        + " install --disable-pip-version-check 'pip>=25.3'; "
        + PIP
        + " install --disable-pip-version-check -r requirements-neural.txt -r doom/requirements.txt "
        "--build-constraint neural-build-constraints.txt 'matplotlib<3.9' "
        "--report /work/install-report.json"
        + SUFFIX
        + "; "
        + PY
        + " -m doom.build_kernel",
        "runtime_prefix": doom_system,
        "native_tests": PY
        + " -m pytest -q --capture=sys -o cache_dir=/work/pytest-cache "
        "--basetemp=/work/pytest-tmp tests/test_doom.py tests/test_doom_reference.py "
        "tests/test_doom_checkpoint.py tests/test_doom_live_training.py tests/test_doom_learning_v6.py",
        "native_tests_reason": "Author baseline, independent Brian2 oracle, real ViZDoom, checkpoint and experimental-learning software fixtures",
        "smoke": PY + " -m doom.server --help",
        "data_prepare": PY
        + " -m doom.connectome malecns_v1; "
        + PY
        + " -m doom.prepare; "
        + PY
        + " -m doom.audit_data",
        "functional": PY + " /work/probes/doom_probe.py",
        "functional_reason": "Full retained MaleCNS graph, original fixed-weight native engine and real RGB/game loop; seeds 1/2/3/1, explicit controls, count/state exports",
        "data_scope": "pinned_MaleCNS_v1_all_retained_edges_fixed_weight_ViZDoom_not_validated_learning_nociception_or_CAP",
    }
    shiu_system = (
        "mkdir -p /work/apt-cache/partial /work/apt-lists/partial; "
        "apt-get -o Dir::State::lists=/work/apt-lists update -qq; "
        "apt-get -o Dir::State::lists=/work/apt-lists -o Dir::Cache::archives=/work/apt-cache "
        "install -y --no-install-recommends build-essential; "
        "dpkg-query -W > /work/system-packages.txt; "
    )
    profiles["SIM-024"].update(
        image="python:3.10-slim@sha256:6ff506466f8b1e981719b468cc0023b8ef000b983cdec0eafe119d01f379e31d",
        environment_storage="docker-volume",
        install=shiu_system
        + "python -m venv /work/env; "
        + PIP
        + " install --disable-pip-version-check pip==26.2.2; "
        + PIP
        + " install --disable-pip-version-check numpy==1.24.4 scipy==1.8.1 pandas==1.4.3 "
        "brian2==2.5.1 Cython==0.29.33 pyarrow==11.0.0 joblib==1.2.0 sympy==1.12 "
        "setuptools==67.8.0 matplotlib==3.7.5 --build-constraint /work/build-constraints.txt "
        "--report /work/install-report.json" + SUFFIX,
        runtime_prefix=shiu_system,
        native_tests=PY + " /work/probes/shiu_probe.py software",
        native_tests_reason="No author test suite; own six-neuron fixture calls original model, Poisson input, outgoing-only silence and SpikeMonitor",
        data_prepare=PY + " /work/probes/shiu_probe.py data",
        functional=PY + " /work/probes/shiu_probe.py full",
        functional_reason="Original v630 graph, original equations/functions, seeded 100-ms sugar runs 1/2/3/1, no-input/output-silencing/two-rate controls and event exports",
        data_scope="pinned_original_Shiu_FlyWire_v630_Brian2_model_no_body_nociception_or_CAP",
    )
    profiles["SIM-004"] = {
        "image": "aspa-sim-escape-octave:20261027",
        "image_build": [
            "docker",
            "build",
            "-t",
            "aspa-sim-escape-octave:20261027",
            "-f",
            "simulations/environments/escape-octave.Dockerfile",
            "simulations/environments",
        ],
        "environment_storage": "docker-volume",
        "install": "python3 -m venv /work/env; "
        + PIP
        + " install --disable-pip-version-check numpy==1.26.4 scipy==1.12.0 pandas==2.2.3 matplotlib==3.9.4 seaborn==0.13.2 statsmodels==0.14.4 openpyxl==3.1.5; "
        + PIP
        + " freeze --all > /work/dependencies.lock.txt; "
        + PIP
        + " check; dpkg-query -W > /work/system-packages.txt; octave --no-gui --quiet --version > /work/octave-version.txt",
        "native_tests": PY + " /work/probes/escape_probe.py inspect",
        "diagnose_after_native_failure": True,
        "smoke": PY + " /work/probes/escape_probe.py smoke",
        "functional": None,
        "data_scope": "real_pinned_analysis_entry_attempts_no_substitute_SCAPE_data",
        "native_tests_reason": "No author suite; actual Octave function compatibility and supplied-data inventory are checked explicitly",
        "functional_reason": "Native processing requires actual author TIFF/MAT/Excel data and GUI assets; no substitute data are supplied",
    }

    reasons = {}
    for row in registry["candidates"]:
        if row["id"] in reasons and not row.get("evaluation", {}).get("result"):
            row["evaluation"] = {
                "status": "blocked",
                "reason": reasons[row["id"]],
                "installation": "not_attempted",
                "biological_validation": False,
            }
        elif row["id"] not in profiles and row["id"] not in reasons:
            raise ValueError("Candidate without a result or profile: " + row["id"])
    # Original Brian2 pins numpy<2, and is explicitly isolated from Python3.12.
    profiles["SIM-006"]["image"] = "python:3.10-slim"
    profiles["SIM-007"]["image"] = "python:3.11-slim"
    profiles["SIM-008"]["image"] = "python:3.11-slim"
    notebook_manifest = WORK / "SIM-008/v09-inputs.json"
    if notebook_manifest.exists():
        import hashlib

        inputs = load(notebook_manifest)
        profiles["SIM-008"]["assets"] = [
            {
                "source": "SIM-008/assets/" + item["file"],
                "destination": "v09/" + item["file"],
                "sha256": item["sha256"],
            }
            for item in inputs["inputs"]
        ] + [
            {
                "source": "SIM-008/v09-inputs.json",
                "destination": "v09/manifest.json",
                "sha256": hashlib.sha256(notebook_manifest.read_bytes()).hexdigest(),
            }
        ]
    profiles["SIM-007"].update(
        functional=PY
        + " /work/probes/malecns_depth_probe.py && "
        + PY
        + " /work/probes/malecns_seed_probe.py",
        data_scope="native_synthetic_checks_and_real_malecns_v1_graph_preparation",
        assets=[
            {
                "source": "SIM-001/20261005T105111Z-6999dc/connectome/raw/" + remote,
                "destination": "malecns/" + local,
                "sha256": digest,
                "primary_url": "https://storage.googleapis.com/flyem-male-cns/v1.0/connectome-data/flat-connectome/"
                + remote,
            }
            for local, remote, digest in [
                (
                    "body-annotations.feather",
                    "body-annotations-male-cns-v1.0-minconf-0.5.feather",
                    "2177e246113e4cfbf1e7772ec37c6da1955ff22e8063d0b1f833101f99a9a3b2",
                ),
                (
                    "body-nt.feather",
                    "body-neurotransmitters-male-cns-v1.0.feather",
                    "95c9289220663abeb3409f3ad9e5a7f8a53f8093f5139d15502cd08da8879621",
                ),
                (
                    "connectome-weights.feather",
                    "connectome-weights-male-cns-v1.0-minconf-0.5.feather",
                    "e35da783d1c686b2b58b3b87cd6a403ae43bfcfba8bff28e08ef752c1a56afc1",
                ),
            ]
        ],
    )
    profiles["SIM-015"].update(
        image="python:3.10-slim@sha256:6ff506466f8b1e981719b468cc0023b8ef000b983cdec0eafe119d01f379e31d",
        environment_storage="docker-volume",
        native_tests_reason="Own four-unit software fixture; no upstream test suite",
        runtime_prefix=(
            "mkdir -p /work/apt-cache/partial /work/apt-lists/partial; "
            "apt-get -o Dir::State::lists=/work/apt-lists update -qq; "
            "apt-get -o Dir::State::lists=/work/apt-lists -o Dir::Cache::archives=/work/apt-cache "
            "install -y --no-install-recommends libegl1 libgl1 libopengl0 libgl1-mesa-dri libglib2.0-0t64; "
            "dpkg-query -W > /work/system-packages.txt; "
        ),
    )
    profiles["SIM-025"].update(
        image="python:3.11-slim@sha256:b7a9e5f6a93d6d4a31f129bbd4bdee69efccb6ded0fb230d78aafaf37af98377",
        environment_storage="docker-volume",
        install="python -m venv /work/env; "
        + PIP
        + " install --disable-pip-version-check . numpy==1.26.4 pandas==2.2.3 "
        "pyarrow==19.0.1 seaborn==0.13.2 scipy==1.13.1 pypdf==6.1.1 "
        "--report /work/install-report.json" + SUFFIX,
        native_tests=PY + " /work/probes/mbi_probe.py software",
        native_tests_reason="No author suite; own threshold-crossing fixtures call original utility, separately from recorded-data reproduction",
        data_prepare=PY + " /work/probes/mbi_probe.py data",
        functional=PY + " -u /work/probes/mbi_probe.py full",
        functional_reason="Seven original author figure scripts on all 72 verified OSF files; explicit TkAgg-to-Agg working-copy adaptation; missing inputs remain failures",
        data_scope="pinned_recorded_benchtop_LFP_stimulation_EMG_analyses_not_neural_or_ECAP_simulator",
    )
    flyconnectome_system = (
        "mkdir -p /work/apt-cache/partial /work/apt-lists/partial; "
        "apt-get -o Dir::State::lists=/work/apt-lists update -qq; "
        "apt-get -o Dir::State::lists=/work/apt-lists -o Dir::Cache::archives=/work/apt-cache "
        "install -y --no-install-recommends build-essential libegl1 libgl1 libopengl0 libgl1-mesa-dri libglib2.0-0t64 libxrender1 libxext6 libsm6; "
        "dpkg-query -W > /work/system-packages.txt; "
    )
    profiles["SIM-026"].update(
        image="python:3.12-slim@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704",
        environment_storage="docker-volume",
        install=flyconnectome_system
        + profiles["SIM-026"]["install"].replace(
            "--disable-pip-version-check ",
            "--disable-pip-version-check --report /work/install-report.json ",
        ),
        runtime_prefix=flyconnectome_system
        + "export VTK_DEFAULT_OPENGL_WINDOW=vtkEGLRenderWindow; ",
        native_tests_reason="No author suite; own uint64 fixture calls the unchanged remap_seg notebook function",
        functional_reason="Four registered tutorial domains: actual segmentation/EM, all 78 neuropils and point lookup, native MeshParty render, separate CAVE query attempt",
    )
    profiles["SIM-027"].update(
        image="python:3.12-slim@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704",
        environment_storage="docker-volume",
        runtime_prefix="export JAX_PLATFORMS=cpu JAX_ENABLE_X64=false; ",
        native_tests_reason="test_configs.py is a Hydra demo; adapter executes it and adds explicit rate-equation and checkpoint checks",
        functional_reason="Unchanged tutorial solver on exact MANC inputs, seeds 1/2/3/1 and explicit raw solver diagnostics",
    )
    profiles["SIM-031"].update(
        image="python:3.12-slim@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704",
        environment_storage="docker-volume",
        install="python -m venv /work/env; "
        + PIP
        + " install --disable-pip-version-check torch==2.14.1+cpu torchvision==0.29.1+cpu --index-url https://download.pytorch.org/whl/cpu --report /work/torch-install.json; "
        + PIP
        + " install --disable-pip-version-check . datamate==1.0.0 numpy==2.5.2 matplotlib==3.11.2 pytest nbformat papermill tabulate ipywidgets --report /work/flyvis-install.json; "
        + PIP
        + " freeze --all > /work/dependencies.lock.txt; "
        + PIP
        + " check",
        runtime_prefix="export FLYVIS_ROOT_DIR=/tmp/aspa-flyvis MPLBACKEND=Agg; "
        + PY
        + " /work/probes/flyvis_prepare.py; ",
        native_tests=PY
        + " -m pytest -q --capture=sys -m 'not slow and not require_large_download and not require_download and not gpu' -o cache_dir=/work/pytest-cache --basetemp=/tmp/aspa-flyvis-tests --junitxml=/work/native-tests.xml && "
        + PY
        + " -m pytest -q --capture=sys tests/test_ensemble.py::test_ensemble_init tests/test_ensemble.py::test_yield_networks -o cache_dir=/work/pytest-cache --basetemp=/tmp/aspa-flyvis-ensemble-tests --junitxml=/work/ensemble-tests.xml",
        smoke=PY + " /work/probes/flyvis_probe.py smoke",
        functional=PY + " -u /work/probes/flyvis_probe.py full",
        data_scope="pinned_Flyvis_optic_lobe_code_and_exact_official_pretrained_ensemble_not_whole_brain",
        native_tests_reason="Native CPU suite excluding declared slow/GPU/download cases, then two real pretrained ensemble tests; fixture data distinguished from real inputs",
        functional_reason="Exact model 000 weights, seeded stimuli 1/2/3/1, native flashes/moving edges, state-hook clamp, zero strength and restore",
    )
    fitting_lock = ROOT / "simulations/environments/fitting-cpu.lock.txt"
    import hashlib

    profiles["SIM-002"].update(
        image="python:3.12-slim@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704",
        environment_storage="docker-volume",
        assets=[
            {
                "source": "SIM-002/assets/fitting-cpu.lock.txt",
                "destination": "fitting-cpu.lock.txt",
                "sha256": hashlib.sha256(fitting_lock.read_bytes()).hexdigest(),
            }
        ],
        install="python -m venv /work/env; "
        + PIP
        + " install --disable-pip-version-check -r /work/assets/fitting-cpu.lock.txt --report /work/install-report.json; "
        + PIP
        + " freeze --all > /work/dependencies.lock.txt; "
        + PIP
        + " check",
        native_tests=PY + " /work/probes/fitting_probe.py software",
        smoke=PY + " /work/probes/fitting_probe.py smoke",
        functional=PY + " -u /work/probes/fitting_probe.py full",
        native_tests_reason="No native suite; actual population step, ID mapping and observed reset/init behavior are checked explicitly",
        functional_reason="Author RAR5 inputs, real full v630 FiringRateNetwork and sparse+LoRA recurrence with untrained parameters; seeds1/2/3/1 and no-input control",
        data_scope="exact_author_v630_archive_and_original_spiking_model_not_paper_fitting_or_human_ECAP",
    )
    profiles["SIM-033"].update(
        image="python:3.12-slim@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704",
        environment_storage="docker-volume",
        native_tests_reason="No author suite for selected notebook; independent normalization and sparse round-trip checks on four actual supplied matrices",
        functional_reason="Native larval AD notebook operations on exact raw table; preserve node map and compare to registered processed matrix by biological IDs",
    )
    profiles["SIM-016"]["image"] = profiles["SIM-012"]["image"]
    profiles["SIM-016"].update(
        native_tests=PY
        + " -m pytest -q --capture=sys -o cache_dir=/work/pytest-cache --basetemp=/work/pytest-tmp",
        data_prepare="ASPA_SOUP_SCRATCH=/tmp/aspa-soup "
        + PY
        + " -u /work/probes/soup_full_probe.py prepare",
        functional=PY
        + " /work/probes/soup_probe.py && ASPA_SOUP_SCRATCH=/tmp/aspa-soup "
        + PY
        + " -u /work/probes/soup_full_probe.py run",
        assets=[dict(item) for item in profiles["SIM-007"]["assets"]],
        data_scope="upstream_four_neuron_fixture_and_registered_full_MaleCNS_v1_fixed_point_CPU_not_biological_validation",
    )
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
    for sid in [
        "SIM-005",
        "SIM-006",
        "SIM-009",
        "SIM-015",
        "SIM-018",
        "SIM-019",
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
    profiles["SIM-006"]["install"] = profiles["SIM-006"]["install"].replace(
        "install torch --index-url https://download.pytorch.org/whl/cpu;",
        "install torch==2.14.1+cpu --index-url https://pypi.org/simple "
        "--extra-index-url https://download.pytorch.org/whl/cpu;",
    )
    profiles["SIM-015"]["install"] = profiles["SIM-015"]["install"].replace(
        "install torch --index-url https://download.pytorch.org/whl/cpu;",
        "install torch==2.14.1+cpu --index-url https://pypi.org/simple "
        "--extra-index-url https://download.pytorch.org/whl/cpu;",
    )
    environment_reference = WORK / "SIM-015/environment-reference.json"
    if environment_reference.is_file():
        reference = load(environment_reference)
        profiles["SIM-015"]["assets"] = [
            {
                "source": reference["source"],
                "destination": "dependencies.lock.txt",
                "sha256": reference["sha256"],
            }
        ]
        profiles["SIM-015"]["install"] = (
            "python -m venv /work/env; "
            + PIP
            + " install --disable-pip-version-check --extra-index-url https://download.pytorch.org/whl/cpu "
            "-r /work/assets/dependencies.lock.txt; "
            + PIP
            + " freeze --all > /work/dependencies.lock.txt; "
            + PIP
            + " check"
        )
    profiles["SIM-009"].update(
        image="aspa-sim-flybox-node22-python:20261025",
        image_build=[
            "docker",
            "build",
            "-t",
            "aspa-sim-flybox-node22-python:20261025",
            "-f",
            "simulations/environments/flybox-node-python.Dockerfile",
            "simulations/environments",
        ],
        install=(
            "python3 -m venv /work/env; "
            + PIP
            + " install --disable-pip-version-check -r backend/requirements.txt; "
            + PIP
            + " freeze --all > /work/dependencies.lock.txt; "
            + PIP
            + " check; "
            "dpkg-query -W > /work/system-packages.txt; "
            "cd frontend; npm install --package-lock-only --ignore-scripts --cache /work/npm-cache --no-audit --no-fund; "
            "npm ci --cache /work/npm-cache --no-audit --no-fund; "
            "npm ls --json > /work/npm-dependency-tree.json; "
            "node --version > /work/node-version.txt; npm --version > /work/npm-version.txt"
        ),
        native_tests=(
            "cd backend; "
            + PY
            + " -m pytest -q --capture=sys -o cache_dir=/work/pytest-cache "
            "--basetemp=/work/pytest-tmp tests/test_core.py; "
            "cd ../frontend; npm run audit:browser; npm run typecheck"
        ),
        smoke=(
            "export PATH=/work/env/bin:$PATH; export FLY_DATA=/work/brain-data; "
            "export VITE_CONNECTOME_BASE=/connectome/; cd frontend; npm run build"
        ),
        functional="node /work/probes/flybox_connectome_probe.mjs",
        data_scope="real_compact_malecns_browser_engine_separate_mock_backend_tests",
    )
    save(PROFILES, profiles)
    save(REGISTRY, registry)
    print(len(profiles), "execution profiles;", len(reasons), "explicit prerequisites")


if __name__ == "__main__":
    main()
