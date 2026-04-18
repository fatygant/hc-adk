"""Minimal in-memory Firestore stand-in for unit tests.

Implements just the surface that `jutra.memory.store` uses:
- `collection(name).document(id).set(data, merge=bool)`
- `document.get()` -> snapshot with `.exists` and `.to_dict()`
- `collection.where(...)`, `order_by(...)`, `limit(...)`, `stream()`
- `collection.count().get()` -> [[AggregationResult(value=int)]]
- `collection.find_nearest(...).stream()` using cosine distance over Vectors.

Not thread-safe, not production-faithful; sufficient for the hackathon tests.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from google.cloud.firestore_v1.vector import Vector


@dataclass
class _Snap:
    id: str
    _data: dict[str, Any] | None

    @property
    def exists(self) -> bool:
        return self._data is not None

    def to_dict(self) -> dict[str, Any]:
        return dict(self._data or {})


@dataclass
class _Doc:
    parent: _Coll
    id: str

    def _slot(self) -> dict[str, Any] | None:
        return self.parent.docs.get(self.id)

    def set(self, data: dict[str, Any], merge: bool = False) -> None:
        if merge and self.id in self.parent.docs:
            self.parent.docs[self.id].update(data)
        else:
            self.parent.docs[self.id] = dict(data)

    def get(self) -> _Snap:
        return _Snap(self.id, self._slot())

    def collection(self, name: str) -> _Coll:
        key = (self.parent.path, self.id, name)
        if key not in self.parent.root.sub_colls:
            self.parent.root.sub_colls[key] = _Coll(
                root=self.parent.root,
                path=f"{self.parent.path}/{self.id}/{name}",
            )
        return self.parent.root.sub_colls[key]


@dataclass
class _AggValue:
    value: int


@dataclass
class _Query:
    coll: _Coll
    filters: list[tuple[str, str, Any]] = field(default_factory=list)
    order: tuple[str, str] | None = None
    lim: int | None = None

    def where(self, field: str, op: str, value: Any) -> _Query:  # noqa: A002
        self.filters.append((field, op, value))
        return self

    def order_by(self, field: str, direction: str = "ASCENDING") -> _Query:  # noqa: A002
        self.order = (field, direction)
        return self

    def limit(self, n: int) -> _Query:
        self.lim = n
        return self

    def _predicate(self, data: dict[str, Any]) -> bool:
        for f, op, v in self.filters:
            if op == "==" and data.get(f) != v:
                return False
        return True

    def stream(self) -> Iterable[_Snap]:
        items = [(doc_id, data) for doc_id, data in self.coll.docs.items() if self._predicate(data)]
        if self.order:
            field, direction = self.order  # noqa: A001
            reverse = direction.lower().startswith("desc")
            items.sort(key=lambda kv: kv[1].get(field, 0), reverse=reverse)
        if self.lim is not None:
            items = items[: self.lim]
        return [_Snap(i, d) for i, d in items]

    def count(self) -> _CountQuery:
        return _CountQuery(self)


@dataclass
class _CountQuery:
    q: _Query

    def get(self) -> list[list[_AggValue]]:
        return [[_AggValue(len(list(self.q.stream())))]]


@dataclass
class _VectorQuery:
    coll: _Coll
    vector_field: str
    query_vector: Vector
    distance_measure: Any
    lim: int

    def stream(self) -> Iterable[_Snap]:
        qv = list(self.query_vector)
        scored: list[tuple[float, str, dict[str, Any]]] = []
        for doc_id, data in self.coll.docs.items():
            emb = data.get(self.vector_field)
            if emb is None:
                continue
            vals = list(emb) if isinstance(emb, Vector) else list(emb)
            if len(vals) != len(qv):
                continue
            scored.append((_cosine(qv, vals), doc_id, data))
        scored.sort(key=lambda s: s[0])
        return [_Snap(d_id, data) for _, d_id, data in scored[: self.lim]]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return 1.0 - (dot / (na * nb))


@dataclass
class _Coll:
    root: FakeFirestore
    path: str
    docs: dict[str, dict[str, Any]] = field(default_factory=dict)

    def document(self, doc_id: str) -> _Doc:
        if doc_id not in self.docs:
            self.docs[doc_id] = {}
            del self.docs[doc_id]
        return _Doc(self, doc_id)

    def where(self, field: str, op: str, value: Any) -> _Query:  # noqa: A002
        return _Query(self).where(field, op, value)

    def order_by(self, field: str, direction: str = "ASCENDING") -> _Query:  # noqa: A002
        return _Query(self).order_by(field, direction)

    def limit(self, n: int) -> _Query:
        return _Query(self).limit(n)

    def stream(self) -> Iterable[_Snap]:
        return _Query(self).stream()

    def count(self) -> _CountQuery:
        return _CountQuery(_Query(self))

    def find_nearest(
        self,
        *,
        vector_field: str,
        query_vector: Vector,
        distance_measure: Any,
        limit: int,
    ) -> _VectorQuery:
        return _VectorQuery(
            coll=self,
            vector_field=vector_field,
            query_vector=query_vector,
            distance_measure=distance_measure,
            lim=limit,
        )


@dataclass
class FakeFirestore:
    top_colls: dict[str, _Coll] = field(default_factory=dict)
    sub_colls: dict[tuple[str, str, str], _Coll] = field(default_factory=dict)

    def collection(self, name: str) -> _Coll:
        if name not in self.top_colls:
            self.top_colls[name] = _Coll(root=self, path=name)
        return self.top_colls[name]
