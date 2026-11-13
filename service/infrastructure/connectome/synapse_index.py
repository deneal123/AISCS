"""Source-batch index for registered MaleCNS neurons; no geometry is invented."""

from __future__ import annotations

import hashlib
import json
import tempfile
from collections import OrderedDict
from pathlib import Path
from threading import Lock

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.ipc as ipc

from service.infrastructure.connectome.synapse_pairs import FIELDS


def file_digest(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm, usedforsecurity=False)
    with path.open("rb") as source:
        while chunk := source.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def build_batch_index(
    source_path: Path, ids_path: Path, output: Path, expected_md5: str, *, progress=None
):
    """Publish only a complete index; one bit marks a possibly relevant batch.

    Each direction is indexed independently. Membership is exact at the batch
    level, not a guarantee that the partner belongs to the registered graph.
    The source and ID file identities are recorded and the bitmap is hashed.
    """
    if output.exists():
        raise FileExistsError("Index destination already exists")
    initial_stat = source_path.stat()
    initial_ids_sha = file_digest(ids_path, "sha256")
    if file_digest(source_path, "md5") != expected_md5:
        raise ValueError("Source checksum mismatch")
    if progress:
        progress("source_verified", 0, 0)
    ids = np.load(ids_path, allow_pickle=False)
    if (ids.ndim != 1 or ids.dtype.kind not in "iu" or not len(ids)
            or np.any(ids[1:] <= ids[:-1]) or np.any(ids <= 0)):
        raise ValueError("Registered neuron IDs must be positive, sorted and unique")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".synapse-index-", dir=output.parent) as temp:
        stage = Path(temp)
        with pa.memory_map(str(source_path), "r") as source:
            reader = ipc.open_file(source)
            if not {"body_pre", "body_post"}.issubset(reader.schema.names):
                raise ValueError("Source schema is incomplete")
            batch_count = reader.num_record_batches
            bits = np.lib.format.open_memmap(
                stage / "batches.npy", mode="w+", dtype=np.uint8,
                shape=(2, len(ids), (batch_count + 7) // 8),
            )
            bits[:] = 0
            for batch_index in range(batch_count):
                batch = reader.get_batch(batch_index)
                for direction, field in enumerate(("body_pre", "body_post")):
                    column = batch.column(field)
                    if column.null_count:
                        raise ValueError("Null neuron ID in source")
                    present = np.unique(column.to_numpy(zero_copy_only=False))
                    positions = np.searchsorted(ids, present)
                    valid = positions < len(ids)
                    positions, present = positions[valid], present[valid]
                    positions = positions[ids[positions] == present]
                    bits[direction, positions, batch_index // 8] |= 1 << (batch_index % 8)
                if progress and ((batch_index + 1) % 250 == 0 or batch_index + 1 == batch_count):
                    progress("indexing", batch_index + 1, batch_count)
            bits.flush()
            del bits
        manifest = {
            "format": "malecns-synapse-batches-v1", "source_md5": expected_md5,
            "source_size": source_path.stat().st_size,
            "ids_sha256": file_digest(ids_path, "sha256"),
            "bitmap_sha256": file_digest(stage / "batches.npy", "sha256"),
            "neurons": len(ids), "batches": batch_count, "directions": ["outgoing", "incoming"],
        }
        final_stat = source_path.stat()
        if ((initial_stat.st_size, initial_stat.st_mtime_ns)
                != (final_stat.st_size, final_stat.st_mtime_ns)
                or manifest["ids_sha256"] != initial_ids_sha):
            raise ValueError("Source or graph IDs changed during indexing")
        (stage / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        stage.rename(output)
    return manifest


class PairQueryLimitExceeded(ValueError):
    """A bounded multi-pair query should fall back to smaller index queries."""


class SynapseBatchIndex:
    """Verify once at open, then query selected source batches without rescanning."""

    def __init__(self, source_path: Path, ids_path: Path, directory: Path, expected_md5: str):
        self.source_path = source_path
        self.ids_path = ids_path
        self.bitmap_path = directory / "batches.npy"
        self.manifest_path = directory / "manifest.json"
        initial_fingerprint = self._fingerprint()
        initial_index_fingerprints = self._index_fingerprints()
        self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        info = self.manifest
        if (info.get("format") != "malecns-synapse-batches-v1"
                or info.get("source_md5") != expected_md5
                or info.get("source_size") != source_path.stat().st_size
                or info.get("ids_sha256") != file_digest(ids_path, "sha256")
                or info.get("bitmap_sha256") != file_digest(directory / "batches.npy", "sha256")
                or file_digest(source_path, "md5") != expected_md5):
            raise ValueError("Synapse index integrity verification failed")
        self.ids = np.load(ids_path, allow_pickle=False, mmap_mode="r")
        self.bits = np.load(directory / "batches.npy", allow_pickle=False, mmap_mode="r")
        if (self.bits.dtype != np.uint8 or self.bits.shape != (
            2, len(self.ids), (info["batches"] + 7) // 8
        ) or len(self.ids) != info["neurons"]):
            raise ValueError("Invalid synapse index dimensions")
        self.source_fingerprint = self._fingerprint()
        self.index_fingerprints = self._index_fingerprints()
        self._cache = OrderedDict()
        self._cache_lock = Lock()
        if self.source_fingerprint != initial_fingerprint:
            raise ValueError("Synapse source changed during verification")
        if self.index_fingerprints != initial_index_fingerprints:
            raise ValueError("Synapse index changed during verification")

    def _fingerprint(self):
        return self._stat_identity(self.source_path)

    @staticmethod
    def _stat_identity(path):
        stat = path.stat()
        return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns

    def _index_fingerprints(self):
        return tuple(self._stat_identity(path) for path in
                     (self.ids_path, self.bitmap_path, self.manifest_path))

    def assert_unchanged(self):
        """Recheck the same file identities used by indexed queries."""
        if self._fingerprint() != self.source_fingerprint:
            raise ValueError("Synapse source changed after verification")
        if self._index_fingerprints() != self.index_fingerprints:
            raise ValueError("Synapse index changed after verification")

    def query_exact_pairs(self, pairs, *, max_rows=100_000):
        """Read complete observations for bounded graph pairs in source order.

        A bitmap intersection selects candidate batches for each pair. Each
        returned row still matches an exact requested pair; a row cap prevents
        this optional optimization from consuming unbounded result memory.
        """
        if (not isinstance(pairs, list) or not 1 <= len(pairs) <= 128
                or any(not isinstance(pair, tuple) or len(pair) != 2
                       or any(type(value) is not int or not 0 < value < 2**63 for value in pair)
                       for pair in pairs)
                or len(set(pairs)) != len(pairs)
                or type(max_rows) is not int or max_rows < 1):
            raise ValueError('Invalid exact synapse pair query')
        self.assert_unchanged()
        mask = np.zeros(self.bits.shape[2], dtype=np.uint8)
        for source, target in pairs:
            positions = np.searchsorted(self.ids, [source, target])
            if any(pos >= len(self.ids) or int(self.ids[pos]) != body
                   for pos, body in zip(positions, (source, target), strict=True)):
                raise ValueError('Neuron is not in registered graph')
            mask |= self.bits[0, positions[0]] & self.bits[1, positions[1]]
        batches = np.flatnonzero(np.unpackbits(mask, bitorder='little')[:self.manifest['batches']])
        sources = pa.array(sorted({source for source, _ in pairs}), type=pa.int64())
        targets = pa.array(sorted({target for _, target in pairs}), type=pa.int64())
        result = {pair: [] for pair in pairs}
        row_count = 0
        with pa.memory_map(str(self.source_path), 'r') as source_file:
            reader = ipc.open_file(source_file)
            if reader.num_record_batches != self.manifest['batches']:
                raise ValueError('Synapse source batch count changed')
            for number in batches:
                batch = reader.get_batch(int(number)).select(FIELDS)
                matches = batch.filter(pc.and_(
                    pc.is_in(batch.column('body_pre'), value_set=sources),
                    pc.is_in(batch.column('body_post'), value_set=targets)))
                for offset in range(0, matches.num_rows, 4096):
                    for row in matches.slice(offset, 4096).to_pylist():
                        pair = (row['body_pre'], row['body_post'])
                        if pair in result:
                            if any(type(row[field]) is not int for field in FIELDS):
                                raise ValueError('Invalid or missing synapse coordinate')
                            row_count += 1
                            if row_count > max_rows:
                                raise PairQueryLimitExceeded(
                                    'Exact synapse pair result exceeds limit')
                            result[pair].append(row)
        self.assert_unchanged()
        return result

    def scan_incoming(self, body_id: int, graph_partners: list[int], active_partners: set[int]):
        """Count graph pairs in one pass and retain only active-partner coordinates."""
        if type(body_id) is not int or not 0 < body_id < 2**63:
            raise ValueError("Invalid neuron ID")
        if (not isinstance(graph_partners, list) or len(set(graph_partners)) != len(graph_partners)
                or any(type(value) is not int or not 0 < value < 2**63
                       for value in graph_partners)
                or not isinstance(active_partners, set)
                or any(type(value) is not int or not 0 < value < 2**63
                       for value in active_partners)):
            raise ValueError("Invalid partner selection")
        position = int(np.searchsorted(self.ids, body_id))
        if position >= len(self.ids) or int(self.ids[position]) != body_id:
            raise ValueError("Neuron is not in registered graph")
        positions = np.searchsorted(self.ids, graph_partners)
        if any(pos >= len(self.ids) or int(self.ids[pos]) != value
               for pos, value in zip(positions, graph_partners, strict=True)):
            raise ValueError("Partner is not in registered graph")
        if self._fingerprint() != self.source_fingerprint:
            raise ValueError("Synapse source changed after verification")
        if self._index_fingerprints() != self.index_fingerprints:
            raise ValueError("Synapse index changed after verification")
        graph_set = pa.array(graph_partners, type=pa.int64())
        active_set = pa.array(sorted(active_partners.intersection(graph_partners)), type=pa.int64())
        batch_mask = np.unpackbits(self.bits[1, position], bitorder="little")
        batch_indices = np.flatnonzero(batch_mask[:self.manifest["batches"]])
        counts, rows = {value: 0 for value in graph_partners}, []
        with pa.memory_map(str(self.source_path), "r") as source:
            reader = ipc.open_file(source)
            if reader.num_record_batches != self.manifest["batches"]:
                raise ValueError("Synapse source batch count changed")
            for batch_index in batch_indices:
                batch = reader.get_batch(int(batch_index)).select(FIELDS)
                matching = batch.filter(pc.equal(batch.column("body_post"), body_id))
                matching = matching.filter(
                    pc.is_in(matching.column("body_pre"), value_set=graph_set)
                )
                if any(column.null_count or not pa.types.is_integer(column.type)
                       for column in matching.columns):
                    raise ValueError("Invalid or missing synapse coordinate")
                values, totals = np.unique(
                    matching.column("body_pre").to_numpy(zero_copy_only=False), return_counts=True
                )
                for value, count in zip(values, totals, strict=True):
                    counts[int(value)] += int(count)
                selected = matching.filter(
                    pc.is_in(matching.column("body_pre"), value_set=active_set)
                )
                rows.extend(selected.to_pylist())
        if self._fingerprint() != self.source_fingerprint:
            raise ValueError("Synapse source changed during query")
        if self._index_fingerprints() != self.index_fingerprints:
            raise ValueError("Synapse index changed during query")
        return {"counts": counts, "pairs": rows, "source_md5": self.manifest["source_md5"],
                "coordinate_frame": "male-cns-v1.0-native-8nm"}

    def query(self, body_id: int, direction: str, limit: int | None = 10000, *, partner_ids=None):
        if type(body_id) is not int or body_id <= 0 or body_id >= 2**63:
            raise ValueError("Invalid neuron ID")
        if (direction not in {"incoming", "outgoing"} or (limit is not None
                and (type(limit) is not int or not 1 <= limit <= 10000))):
            raise ValueError("Invalid direction or row limit")
        if self._fingerprint() != self.source_fingerprint:
            raise ValueError("Synapse source changed after verification")
        if self._index_fingerprints() != self.index_fingerprints:
            raise ValueError("Synapse index changed after verification")
        position = int(np.searchsorted(self.ids, body_id))
        if position >= len(self.ids) or int(self.ids[position]) != body_id:
            raise ValueError("Neuron is not in registered graph")
        if partner_ids is not None:
            if (not isinstance(partner_ids, list | tuple) or len(partner_ids) > 20
                    or any(type(value) is not int or value <= 0 or value >= 2**63
                           for value in partner_ids) or len(set(partner_ids)) != len(partner_ids)):
                raise ValueError("Invalid partner IDs")
            partner_positions = np.searchsorted(self.ids, partner_ids)
            if any(pos >= len(self.ids) or int(self.ids[pos]) != value
                   for pos, value in zip(partner_positions, partner_ids, strict=True)):
                raise ValueError("Partner is not in registered graph")
        cache_key = (body_id, direction, limit, None if partner_ids is None else tuple(partner_ids))
        if limit is not None:
            with self._cache_lock:
                cached = self._cache.get(cache_key)
                if cached is not None:
                    if self._fingerprint() != self.source_fingerprint:
                        raise ValueError("Synapse source changed after verification")
                    if self._index_fingerprints() != self.index_fingerprints:
                        raise ValueError("Synapse index changed after verification")
                    self._cache.move_to_end(cache_key)
                    return json.loads(cached)
        direction_index = 0 if direction == "outgoing" else 1
        selected_bits = self.bits[direction_index, position]
        if partner_ids is not None:
            partner_bits = self.bits[1 - direction_index, partner_positions]
            other_bits = (np.bitwise_or.reduce(partner_bits, axis=0) if len(partner_ids)
                          else np.zeros_like(selected_bits))
            selected_bits = np.bitwise_and(selected_bits, other_bits)
        batch_mask = np.unpackbits(selected_bits, bitorder="little")
        batch_indices = np.flatnonzero(batch_mask[:self.manifest["batches"]])
        rows, total, partner_counts = [], 0, {}
        with pa.memory_map(str(self.source_path), "r") as source:
            reader = ipc.open_file(source)
            if reader.num_record_batches != self.manifest["batches"]:
                raise ValueError("Synapse source batch count changed")
            for batch_index in batch_indices:
                batch = reader.get_batch(int(batch_index)).select(FIELDS)
                field = "body_pre" if direction == "outgoing" else "body_post"
                matching = batch.filter(pc.equal(batch.column(field), body_id))
                partner_field = "body_post" if direction == "outgoing" else "body_pre"
                if partner_ids is not None:
                    matching = matching.filter(pc.is_in(
                        matching.column(partner_field),
                        value_set=pa.array(partner_ids, type=pa.int64()),
                    ))
                    values, counts = np.unique(
                        matching.column(partner_field).to_numpy(zero_copy_only=False),
                        return_counts=True,
                    )
                    for value, count in zip(values, counts, strict=True):
                        key = str(int(value))
                        partner_counts[key] = partner_counts.get(key, 0) + int(count)
                total += matching.num_rows
                remaining = matching.num_rows if limit is None else max(0, limit - len(rows))
                for row in matching.slice(0, remaining).to_pylist():
                    if any(type(row[field]) is not int for field in FIELDS):
                        raise ValueError("Invalid or missing synapse coordinate")
                    rows.append(row)
        if self._fingerprint() != self.source_fingerprint:
            raise ValueError("Synapse source changed during query")
        if self._index_fingerprints() != self.index_fingerprints:
            raise ValueError("Synapse index changed during query")
        result = {"body_id": str(body_id), "direction": direction, "total": total,
                  "returned": len(rows), "truncated": total > len(rows),
                  "coordinate_frame": "male-cns-v1.0-native-8nm",
                  "source_md5": self.manifest["source_md5"], "pairs": rows}
        if partner_ids is not None:
            result["partner_counts"] = {str(value): partner_counts.get(str(value), 0)
                                        for value in partner_ids}
        if limit is not None:
            with self._cache_lock:
                self._cache[cache_key] = json.dumps(result, separators=(",", ":"))
                self._cache.move_to_end(cache_key)
                while len(self._cache) > 8:
                    self._cache.popitem(last=False)
        return result


def registered_page_pairs(index, graph, body_id: int, direction: str, offset: int, limit: int,
                          *, all_pairs: bool = False):
    """Compare source pairs with one bounded page of registered graph edges."""
    from service.infrastructure.connectome.neighbors import incoming, outgoing

    if (type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 20
            or type(all_pairs) is not bool):
        raise ValueError("Invalid graph page")
    if index.manifest["ids_sha256"] != graph.provenance["array_sha256"]["ids.npy"]:
        raise ValueError("Synapse index and graph neuron IDs differ")
    if direction == "outgoing":
        page, key = outgoing(graph, body_id, offset, limit), "target_id"
    elif direction == "incoming":
        page, key = incoming(graph, body_id, offset, limit), "source_id"
    else:
        raise ValueError("Invalid direction")
    partners = [int(item[key]) for item in page["items"]]
    result = index.query(body_id, direction, limit=None if all_pairs else 10000,
                         partner_ids=partners)
    comparison = [{"partner_id": item[key], "graph_synapses": item["synapse_count"],
                   "source_pairs": result["partner_counts"][item[key]]}
                  for item in page["items"]]
    return {**result, "graph_manifest_sha256": page["manifest_sha256"],
            "graph_offset": offset, "graph_next_offset": page["next_offset"],
            "edge_counts": comparison,
            "counts_match": all(row["graph_synapses"] == row["source_pairs"]
                                for row in comparison)}
