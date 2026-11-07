"""Archive selected solved cells for differential rerecording, without rerunning neurons.

The archive remains an engineering model of the explicitly selected cells; it
does not establish whole-network currents or biological calibration. The
manifest hash must come from a trusted owner-controlled run record.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import numpy as np

from service.infrastructure.stimulation.network_recording import record_independent_cells

FIELDS = (
    "time_ms",
    "starts_um",
    "ends_um",
    "midpoints_um",
    "endpoint_radii_um",
    "diameters_um",
    "voltage_mv",
    "membrane_current_na",
    "field_mv",
    "stimulation_parameters",
    "stimulus_fraction",
    "synaptic_events_sha256",
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _stream_sha(stream) -> str:
    digest = hashlib.sha256()
    stream.seek(0)
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


class CurrentArchiveWriter:
    """Incremental writer; publish the manifest only after every cell succeeds."""

    def __init__(self, directory: Path, electrode_um, reference_um, *, source_model="pointsource"):
        directory.mkdir(parents=True, exist_ok=False)
        self.directory = directory
        self.electrode_um, self.reference_um = electrode_um, reference_um
        self.source_model = source_model
        self.entries, self.seen = [], set()
        self.baseline_time = self.baseline_stim = self.baseline_parameters = None
        self.failed = self.finished = False

    def add(self, solution, provenance):
        if self.failed or self.finished:
            raise ValueError("Current archive writer is closed")
        try:
            self._add(solution, provenance)
        except Exception:
            self.failed = True
            raise

    def _add(self, solution, provenance):
        checked = record_independent_cells(
            [(solution, provenance)],
            self.electrode_um,
            self.reference_um,
            source_model=self.source_model,
        )
        body = provenance["body_id"]
        if body in self.seen:
            raise ValueError("Duplicate current source")
        time, stim = checked["time_ms"], checked["stimulus_fraction"]
        parameters = checked["stimulation_parameters"]
        if self.baseline_time is None:
            self.baseline_time, self.baseline_stim = time.copy(), stim.copy()
            self.baseline_parameters = parameters
        elif (
            not np.array_equal(time, self.baseline_time)
            or not np.array_equal(stim, self.baseline_stim)
            or parameters != self.baseline_parameters
        ):
            raise ValueError("Current sources do not share stimulation and time grid")
        try:
            metadata = json.dumps(
                provenance,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid current provenance") from exc
        arrays = {key: np.asarray(solution[key]) for key in FIELDS}
        if any(array.dtype.hasobject for array in arrays.values()):
            raise ValueError("Object arrays are not supported")
        name = f"cell-{len(self.entries):06d}.npz"
        path = self.directory / name
        with path.open("xb") as output:
            np.savez_compressed(
                output, **arrays, provenance=np.frombuffer(metadata, dtype=np.uint8)
            )
        with path.open("rb") as source:
            digest = _stream_sha(source)
        self.entries.append(
            {"file": name, "sha256": digest, "bytes": path.stat().st_size, "body_id": body}
        )
        self.seen.add(body)

    def finish(self):
        if self.failed or self.finished or not self.entries:
            raise ValueError("Current archive is incomplete or closed")
        payload = (
            json.dumps(
                {"format": "selected-current-archive-v1", "cells": self.entries},
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
        temporary = self.directory / "manifest.pending"
        try:
            with temporary.open("xb") as output:
                if output.write(payload) != len(payload):
                    raise OSError("Incomplete current manifest write")
            temporary.rename(self.directory / "manifest.json")
        except OSError:
            self.failed = True
            raise
        self.finished = True
        return _sha(payload)


def write_current_archive(
    records, directory: Path, electrode_um, reference_um, *, source_model="pointsource"
) -> str:
    """Write verified solutions incrementally; publish the manifest last."""
    writer = CurrentArchiveWriter(directory, electrode_um, reference_um, source_model=source_model)
    for solution, provenance in records:
        writer.add(solution, provenance)
    return writer.finish()


def rerecord_current_archive(
    directory: Path,
    expected_manifest_sha256: str,
    electrode_um,
    reference_um,
    *,
    source_model="pointsource",
):
    """Recompute selected-cell channels from a trusted manifest and verified files."""
    if not isinstance(expected_manifest_sha256, str) or not re.fullmatch(
        r"[a-f0-9]{64}", expected_manifest_sha256
    ):
        raise ValueError("A trusted manifest digest is required")
    payload = (directory / "manifest.json").read_bytes()
    if _sha(payload) != expected_manifest_sha256:
        raise ValueError("Current archive manifest mismatch")
    manifest = json.loads(payload)
    if (
        not isinstance(manifest, dict)
        or manifest.get("format") != "selected-current-archive-v1"
        or not isinstance(manifest.get("cells"), list)
        or not manifest["cells"]
    ):
        raise ValueError("Invalid current archive manifest")

    def records():
        for index, entry in enumerate(manifest["cells"]):
            if (
                not isinstance(entry, dict)
                or entry.get("file") != f"cell-{index:06d}.npz"
                or type(entry.get("bytes")) is not int
                or entry["bytes"] <= 0
                or not isinstance(entry.get("sha256"), str)
                or not re.fullmatch(r"[a-f0-9]{64}", entry["sha256"])
            ):
                raise ValueError("Invalid current archive entry")
            path = directory / entry["file"]
            if path.stat().st_size != entry["bytes"]:
                raise ValueError("Current archive file size mismatch")
            with path.open("rb") as stream:
                if _stream_sha(stream) != entry["sha256"]:
                    raise ValueError("Current archive file checksum mismatch")
                stream.seek(0)
                with np.load(stream, allow_pickle=False) as loaded:
                    if set(loaded.files) != {*FIELDS, "provenance"}:
                        raise ValueError("Invalid current archive arrays")
                    provenance = json.loads(loaded["provenance"].tobytes().decode("utf-8"))
                    solution = {key: loaded[key] for key in FIELDS}
                if _stream_sha(stream) != entry["sha256"]:
                    raise ValueError("Current archive file changed during reading")
            if not isinstance(provenance, dict) or provenance.get("body_id") != entry.get(
                "body_id"
            ):
                raise ValueError("Current archive identity mismatch")
            yield solution, provenance

    result = record_independent_cells(
        records(), electrode_um, reference_um, source_model=source_model
    )
    return {
        **result,
        "current_archive_sha256": expected_manifest_sha256,
        "interpretation": "rerecording selected independent cells; no whole-network currents",
    }
