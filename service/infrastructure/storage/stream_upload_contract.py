"""Known-length upload bounds shared by native storage adapters."""


def validate_upload_length(length: int) -> int:
    # Unknown-length SDK mode is not part of our seekable upload contract.
    # In particular, bool must never mean a one-byte or empty successful upload.
    if type(length) is not int or length < 0:
        raise ValueError("storage_stream_invalid")
    return length


def validate_upload_chunk(chunk: object, requested: int) -> bytes:
    if not isinstance(chunk, bytes) or len(chunk) > requested:
        raise ValueError("storage_stream_invalid")
    if not chunk:
        raise OSError("storage_stream_incomplete")
    return chunk
