"""Физически отдельные коллекции Qdrant для разных моделей и размерностей."""

import re
import threading

from collections import defaultdict

from memos.embedders.space import SpaceVector
from memos.vec_dbs.item import VecDBItem
from memos.vec_dbs.qdrant import QdrantVecDB


_NAME = re.compile(r"gpthub_memory_([0-9a-f]{32})_([1-9][0-9]*)")


class SpaceAwareQdrantVecDB(QdrantVecDB):
    def __init__(self, config):
        super().__init__(config)
        self._spaces = {}
        self._space_lock = threading.RLock()

    def _space(self, space, dimension):
        name = f"gpthub_memory_{space}_{dimension}"
        if not _NAME.fullmatch(name):
            raise ValueError("invalid_embedding_space")
        with self._space_lock:
            if name not in self._spaces:
                config = self.config.model_copy(
                    update={
                        "collection_name": name,
                        "vector_dimension": dimension,
                    }
                )
                self._spaces[name] = QdrantVecDB(config)
            return self._spaces[name]

    def _stores(self):
        yield self
        for name in self.list_collections():
            match = _NAME.fullmatch(name)
            if match:
                yield self._space(match[1], int(match[2]))

    def search(self, query_vector, top_k, filter=None):
        space = getattr(query_vector, "space", None)
        if not space:
            return super().search(query_vector, top_k, filter)
        return self._space(space, len(query_vector)).search(query_vector, top_k, filter)

    def add(self, data):
        groups = defaultdict(list)
        for raw in data:
            item = VecDBItem.from_dict(raw) if isinstance(raw, dict) else raw
            space = (item.payload or {}).get("embedding_space")
            store = self._space(space, len(item.vector)) if space and item.vector else self
            groups[store].append(item)
        for store, items in groups.items():
            QdrantVecDB.add(store, items)

    def update(self, id, data):
        if isinstance(data, dict):
            data = VecDBItem.from_dict(data)
        if data.vector:
            return self.add([data.model_copy(update={"id": id})])
        for store in self._stores():
            if QdrantVecDB.get_by_id(store, id):
                QdrantVecDB.update(store, id, data)

    def get_by_ids(self, ids):
        result = []
        for store in self._stores():
            for item in QdrantVecDB.get_by_ids(store, ids):
                space = (item.payload or {}).get("embedding_space")
                if item.vector and space:
                    item.vector = SpaceVector(item.vector, space)
                result.append(item)
        return result

    def get_by_id(self, id):
        items = self.get_by_ids([id])
        return items[-1] if items else None

    def get_for_space(self, id, space):
        for item in self.get_by_ids([id]):
            if getattr(item.vector, "space", None) == space:
                return item
        return None

    def get_by_filter(self, filter, scroll_limit=100):
        return [
            item
            for store in self._stores()
            for item in QdrantVecDB.get_by_filter(store, filter, scroll_limit)
        ]

    def delete(self, ids):
        for store in self._stores():
            QdrantVecDB.delete(store, ids)

    def count(self, filter=None):
        return sum(QdrantVecDB.count(store, filter) for store in self._stores())

    def wipe_spaces(self):
        stores = list(self._stores())
        for store in stores:
            store.client.delete_collection(store.config.collection_name)
        self._spaces.clear()
        self.create_collection()
