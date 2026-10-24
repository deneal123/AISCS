"""Закреплённые кандидаты только для сравнения, не каталог продуктового провайдера."""

from dataclasses import dataclass

from local_llm.service.domain.model import Artifact


@dataclass(frozen=True)
class Candidate:
    artifact: Artifact
    source: str
    revision: str
    license: str
    memory_bytes: int


def candidate(repo, revision, filename, digest, size, memory, license="apache-2.0"):
    return Candidate(
        Artifact(
            filename, f"https://huggingface.co/{repo}/resolve/{revision}/{filename}", digest, size
        ),
        repo,
        revision,
        license,
        memory,
    )


CANDIDATES = {
    "baseline": candidate(
        "LiquidAI/LFM2.5-1.2B-Instruct-GGUF",
        "8ed288026e23958ad9dfa92d53ed773a8eee7125",
        "LFM2.5-1.2B-Instruct-Q4_K_M.gguf",
        "b1b3de114215d9507409a662a501a631095a479a419584e8a2ded6304b19b4f5",
        730895168,
        1536 * 1024**2,
        license="lfm1.0",
    ),
    "luma": candidate(
        "LUMAMODEL/luma",
        "20b745be469b190df736a3ee1fa6d462e3911423",
        "luma-q8_0.gguf",
        "610639753c0f7645201e2d6826cde6ca87aca8c5e2a53cde970d7cc6c135a733",
        531068384,
        1536 * 1024**2,
    ),
    "noir": candidate(
        "mradermacher/Noir-lightning-GGUF",
        "7a9efdcae5257b36851bbfa9c0e8f5ee06a32505",
        "Noir-lightning.Q8_0.gguf",
        "f44d39715c56ac7799584c2635b82d682e5be7ff9022918554a6d827963fdaed",
        531068512,
        1536 * 1024**2,
    ),
    "t-lite": candidate(
        "t-tech/T-lite-it-2.1-GGUF",
        "fc10186e59064c2e74f59c3d5dbce233931b3b81",
        "T-lite-it-2.1-Q4_K_M.gguf",
        "68c75f5940c36baca18113058ad3d55f6d1d3e1123a8053bb4bba8481805c960",
        5027750240,
        7 * 1024**3,
    ),
    "qwen35": candidate(
        "ggml-org/Qwen3.5-0.8B-GGUF",
        "807dfd9a6fadbf703207aac3bfb0b2b3040d077c",
        "Qwen3.5-0.8B-Q8_0.gguf",
        "37ae482d336108d23516fa35e8e0c4126688d81018b87178a18d752a1357814f",
        833592096,
        1536 * 1024**2,
    ),
    "qwen3": candidate(
        "Qwen/Qwen3-0.6B-GGUF",
        "23749fefcc72300e3a2ad315e1317431b06b590a",
        "Qwen3-0.6B-Q8_0.gguf",
        "9465e63a22add5354d9bb4b99e90117043c7124007664907259bd16d043bb031",
        639446688,
        1536 * 1024**2,
    ),
    "qwen25": candidate(
        "Qwen/Qwen2.5-1.5B-Instruct-GGUF",
        "91cad51170dc346986eccefdc2dd33a9da36ead9",
        "qwen2.5-1.5b-instruct-q4_k_m.gguf",
        "6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e",
        1117320736,
        1536 * 1024**2,
    ),
    "granite": candidate(
        "ibm-granite/granite-4.0-350m-GGUF",
        "b8208a86a58427e1739265318028eb5895b74bf2",
        "granite-4.0-350m-Q8_0.gguf",
        "9595dafb4ed15aa02512c8ea26188744192a6f09530eae0a2747bd3ada96cd36",
        378138016,
        1536 * 1024**2,
    ),
    "qwen35-2b": candidate(
        "bartowski/Qwen_Qwen3.5-2B-GGUF",
        "7d26695454df6de5fbcce2e58681e62dae06ce43",
        "Qwen_Qwen3.5-2B-Q4_K_S.gguf",
        "55b574899b75180d084238ffbf5d3d165c568a3d73e1edbd3c826682a986c8d4",
        1327696992,
        1536 * 1024**2,
    ),
    "granite1b": candidate(
        "ibm-granite/granite-4.0-h-1b-GGUF",
        "c2cb1972f511add21f3bae244990b8ff3a3ffb23",
        "granite-4.0-h-1b-Q4_K_M.gguf",
        "da3d737121a96f3c9a316685212376257a7f167b74380855666dd488d6af3bcb",
        901162208,
        1536 * 1024**2,
    ),
    "qwen25-coder": candidate(
        "Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF",
        "f86cb2c1fa58255f8052cc32aeede1b7482d4361",
        "qwen2.5-coder-1.5b-instruct-q4_k_m.gguf",
        "cc324af070c2ecbfd324a30884d2f951a7ff756aba85cb811a6ec436933bb046",
        1117320768,
        1536 * 1024**2,
    ),
}


def artifact_for(name):
    """Файл хранится плоско; путь исходного репозитория остаётся только в URL."""
    from dataclasses import replace
    from pathlib import PurePosixPath

    artifact = CANDIDATES[name].artifact
    return replace(artifact, filename=PurePosixPath(artifact.filename).name)


def require_dev_candidate(name, env):
    """Не допускаем случайный запуск сравнения с project/volume production."""
    if env.get("GPTHUB_MODEL_COMPARISON") != "dev-only":
        raise ValueError("comparison_dev_opt_in_required")
    if env.get("GPTHUB_COMPARISON_PROJECT") != "gpthub-dev":
        raise ValueError("comparison_project_invalid")
    if env.get("GPTHUB_COMPARISON_CANDIDATE") != name:
        raise ValueError("comparison_candidate_mismatch")
