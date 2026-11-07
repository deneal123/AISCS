"""Transfer an owned current archive and validate its bounded rerecording preview."""

from __future__ import annotations

import hashlib
import json
import math
import tempfile

from service.infrastructure.storage.bounded_download import settled_thread
from service.services.simulations.inputs.current_source import CurrentSource


class RerecordError(ValueError):
    pass


def validate_rerecord_preview(value, source: CurrentSource, electrode, reference):
    try:
        config = source.configuration
        simulation = config["simulation"]
        count, shown, cells = value["samples"], value["shown_samples"], value["cells"]
        minimum_stimulus = (
            -1.000000000001 if simulation.get("pulse_shape") == "biphasic" else -1e-12
        )
        names = ("time_ms", "neural_uv", "stimulus_artifact_uv", "total_uv", "stimulus_fraction")
        arrays = [value[name] for name in names]
        if (
            type(count) is not int
            or count != round(simulation["duration_ms"] / simulation["dt_ms"]) + 1
            or type(shown) is not int
            or not 2 <= shown <= min(count, 4096)
            or type(cells) is not int
            or cells != len(config["source_cells"]) + len(config["replay_ids"])
            or any(not isinstance(row, list) or len(row) != shown for row in arrays)
            or any(
                type(item) not in (int, float) or not math.isfinite(item)
                for row in arrays
                for item in row
            )
            or not math.isclose(arrays[0][0], 0, abs_tol=1e-8)
            or not math.isclose(arrays[0][-1], simulation["duration_ms"], abs_tol=1e-8)
            or any(a >= b for a, b in zip(arrays[0], arrays[0][1:], strict=False))
            or any(
                abs(t - round(t / simulation["dt_ms"]) * simulation["dt_ms"])
                > max(1e-8, simulation["dt_ms"] * 1e-6)
                for t in arrays[0]
            )
            or any(sample < minimum_stimulus or sample > 1.000000000001 for sample in arrays[4])
            or value["electrode_um"] != list(electrode)
            or value["reference_um"] != list(reference)
            or value["package_sha256"] != source.sha256
            or value["current_manifest_sha256"] != source.manifest_sha256
            or value["source_model"] != simulation["source_model"]
            or value["coordinate_frame"] != "MaleCNS native EM, micrometres"
            or value["interpretation"]
            != "rerecording selected independent cells; no whole-network currents"
            or any(
                not math.isclose(n + a, total, rel_tol=1e-10, abs_tol=1e-8)
                for n, a, total in zip(arrays[1], arrays[2], arrays[3], strict=True)
            )
        ):
            raise RerecordError("invalid_preview")
        acquisition = value.get("acquisition")
        if (config.get("acquisition") is None) != (acquisition is None):
            raise RerecordError("invalid_preview")
        if acquisition is not None:
            filtered, valid, saturated = (
                acquisition[name]
                for name in ("filtered_total_uv", "valid_samples", "saturated_samples")
            )
            if (
                any(
                    not isinstance(row, list) or len(row) != shown
                    for row in (filtered, valid, saturated)
                )
                or any(
                    type(item) not in (int, float) or not math.isfinite(item) for item in filtered
                )
                or any(type(item) is not bool for item in valid + saturated)
                or any(v and s for v, s in zip(valid, saturated, strict=True))
                or any(
                    acquisition["settings"].get(key) != config["acquisition"].get(key)
                    for key in ("low_hz", "high_hz", "recovery_ms", "clip_uv")
                )
            ):
                raise RerecordError("invalid_preview")
            intervals = acquisition.get("mask_intervals")
            if (
                acquisition.get("mask_scope") != "conservative aggregation over the source bin"
                or not isinstance(intervals, list)
                or not 1 <= len(intervals) <= 341
            ):
                raise RerecordError("invalid_preview")
            previous = 0.0
            for interval in intervals:
                start, end = interval["start_ms"], interval["end_ms"]
                valid_interval, clipped = interval["valid"], interval["saturated"]
                if (
                    type(start) not in (int, float)
                    or not math.isfinite(start)
                    or type(end) not in (int, float)
                    or not math.isfinite(end)
                    or not math.isclose(start, previous, rel_tol=0, abs_tol=1e-8)
                    or end < start
                    or end > simulation["duration_ms"] + 1e-8
                    or type(valid_interval) is not bool
                    or type(clipped) is not bool
                    or (valid_interval and clipped)
                ):
                    raise RerecordError("invalid_preview")
                previous = end
            if not math.isclose(previous, simulation["duration_ms"], rel_tol=0, abs_tol=1e-8):
                raise RerecordError("invalid_preview")
            index = 0
            for t, valid_sample, saturated_sample in zip(arrays[0], valid, saturated, strict=True):
                while index < len(intervals) - 1 and t > intervals[index]["end_ms"]:
                    index += 1
                interval = intervals[index]
                if valid_sample != interval["valid"] or saturated_sample != interval["saturated"]:
                    raise RerecordError("invalid_preview")
    except (KeyError, TypeError, ValueError, ZeroDivisionError, OverflowError) as exc:
        raise RerecordError("invalid_preview") from exc
    return value


async def transfer_rerecord(storage, client, source: CurrentSource, electrode, reference):
    simulation = source.configuration["simulation"]
    params = {
        "package_sha256": source.sha256,
        "current_manifest_sha256": source.manifest_sha256,
        "electrode_um": list(electrode),
        "reference_um": list(reference),
        "source_model": simulation["source_model"],
        "acquisition": source.configuration.get("acquisition"),
    }
    with tempfile.SpooledTemporaryFile(max_size=1024 * 1024, mode="w+b") as stream:
        size = await storage.download_file_stream(
            file_key=source.storage_key, target=stream, max_bytes=source.size
        )
        if size != source.size or stream.tell() != source.size:
            raise RerecordError("source_size_mismatch")

        def checksum():
            stream.seek(0)
            digest = hashlib.sha256()
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
            stream.seek(0)
            return digest.hexdigest()

        if await settled_thread(checksum) != source.sha256:
            raise RerecordError("source_checksum_mismatch")

        async def chunks():
            while chunk := await settled_thread(lambda: stream.read(1024 * 1024)):
                yield chunk

        async with client.stream(
            "POST",
            "/v1/rerecord-preview",
            content=chunks(),
            timeout=120.0,
            headers={
                "X-Recording-Configuration": json.dumps(params, separators=(",", ":")),
                "Content-Length": str(source.size),
            },
        ) as response:
            response.raise_for_status()
            data = bytearray()
            async for chunk in response.aiter_bytes():
                if len(data) + len(chunk) > 2 * 1024 * 1024:
                    raise RerecordError("preview_too_large")
                data.extend(chunk)
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, ValueError) as exc:
        raise RerecordError("invalid_preview") from exc
    return validate_rerecord_preview(value, source, electrode, reference)
