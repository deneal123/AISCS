"""Restore model 000 from the official author-hashed FlyVis archive."""

import hashlib
import zipfile

SHA256 = "71c78d4070556a536b13b23ee3139cd2788aa2a9d07d430a223b4edead281db1"
PREFIX = "results/flow/0000/000/"
FILES = (
    "_meta.yaml",
    "best_chkpt",
    "validation_loss.h5",
    "chkpts/chkpt_00000",
    "validation/loss.h5",
)


def hydrate(run):
    from inventory import ROOT, WORK, save
    from simctl import checked_work

    run = checked_work(run)
    if run.parent.name != "SIM-019":
        raise ValueError("Pretrained input requires an owned SIM-019 run")
    archive = WORK / "SIM-019/assets/results_pretrained_models.zip"
    if not archive.is_file():
        raise ValueError(
            "Acquire the official FlyVis pretrained archive using its registered downloader; no substitute weights"
        )
    with archive.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != SHA256:
        raise ValueError("Official pretrained archive checksum mismatch")
    records = []
    with zipfile.ZipFile(archive) as bundle:
        for name in FILES:
            member = PREFIX + name
            data = bundle.read(member)
            target = checked_work(run / "assets/pretrained" / member)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            records.append(
                {
                    "member": member,
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "bytes": len(data),
                    "destination": target.relative_to(run).as_posix(),
                }
            )
    save(
        run / "pretrained-inputs.json",
        {
            "model": "flow/0000/000",
            "archive": archive.relative_to(ROOT).as_posix(),
            "sha256": SHA256,
            "files": records,
            "primary_source": "SIM-031 pinned flyvis_cli/download_pretrained_models.py",
            "scope": "official pretrained weights, not a fresh or fabricated replacement",
        },
    )
