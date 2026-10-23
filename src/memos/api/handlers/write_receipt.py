"""Подтверждение записи чтением графа и фактического вектора из хранилища."""

from memos.configs.gateway import managed_memory_enabled


def indexed_results(graph_db, results):
    verified = []
    for item in results:
        if not isinstance(item, dict) or not item.get("memory_id") or not item.get("cube_id"):
            return None
        try:
            node = graph_db.get_node(item["memory_id"], user_name=item["cube_id"])
            metadata = (node or {}).get("metadata") or {}
            if metadata.get("vector_sync") != "success" or not metadata.get("embedding"):
                return None
            if managed_memory_enabled() and not metadata.get("embedding_space"):
                return None
            verified.append({**item, "indexed": True})
        except Exception:
            return None
    return verified
