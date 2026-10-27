class TempFilesManager:
    """Compatibility name for connection-local attachment references.

    Chat intake creates durable Library sources. Their retention is independent
    of a WebSocket connection; only an explicit owner deletion may remove them.
    """

    @staticmethod
    def register_temp_file_ids(session: dict, file_ids: list[str]) -> None:
        bucket = session.setdefault("_temp_file_ids", set())
        if not isinstance(bucket, set):
            bucket = set(bucket) if isinstance(bucket, (list, tuple)) else set()
            session["_temp_file_ids"] = bucket
        for item in file_ids:
            file_id = str(item).strip()
            if file_id:
                bucket.add(file_id)

    @staticmethod
    async def cleanup_temp_files(session: dict, file_service) -> None:
        # Historical uploads were temporary; S21+ uploads are durable UserFiles.
        # Never feed these IDs to FileSaverService.delete on disconnect/replay.
        session.pop("_temp_file_ids", None)
