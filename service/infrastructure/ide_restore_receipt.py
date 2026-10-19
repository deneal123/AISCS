"""Fixed, bounded completion marker outside the repository and its capsule."""

from __future__ import annotations

import errno
import hmac
import os
import stat

from infrastructure.ide_bundle_format import BundleFailure

NAME = ".gpthub-ide-restored-v1"


def receipt(proof: str, *, write: bool) -> bool:
    if (
        type(proof) is not str
        or len(proof) != 64
        or any(c not in "0123456789abcdef" for c in proof)
    ):
        raise BundleFailure()
    expected = proof.encode("ascii")
    directory = os.open("/tmp", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        flags = os.O_NOFOLLOW | os.O_NONBLOCK
        flags |= os.O_WRONLY | os.O_CREAT | os.O_EXCL if write else os.O_RDONLY
        try:
            target = os.open(NAME, flags, 0o600, dir_fd=directory)
        except OSError as error:
            if not write and error.errno in {errno.ENOENT, errno.ELOOP, errno.ENXIO}:
                return False
            raise BundleFailure("ide_bundle_unavailable") from None
        try:
            info = os.fstat(target)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                return False
            if write:
                if os.write(target, expected) != len(expected):
                    raise BundleFailure("ide_bundle_unavailable")
                os.fsync(target)
                return True
            return info.st_size == 64 and hmac.compare_digest(os.read(target, 65), expected)
        finally:
            os.close(target)
    finally:
        os.close(directory)
