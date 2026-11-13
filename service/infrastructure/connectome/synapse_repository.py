"""One verified read-only source/index instance per generator process."""

from functools import lru_cache
from pathlib import Path
from threading import Lock

from service.infrastructure.connectome.synapse_index import SynapseBatchIndex

SOURCE_MD5 = "58efcf712f8c4d4de5f2ad51e97def76"
SOURCE_NAME = "syn-partners-male-cns-v1.0-minconf-0.5.feather"
_lock = Lock()


@lru_cache(maxsize=1)
def _open_index(root: Path, ids: Path):
    return SynapseBatchIndex(root / SOURCE_NAME, ids, root / "index-v1", SOURCE_MD5)


def registered_index(root: Path, ids: Path):
    # lru_cache alone permits concurrent duplicate initialization on cache misses.
    with _lock:
        index = _open_index(root, ids)
        # A cached object is only valid while every verified backing file has
        # retained its identity. Do not silently reopen or bypass verification.
        index.assert_unchanged()
        return index
