"""Regroup checked morphology chunks into bounded GPU batches without copying geometry."""

from __future__ import annotations


def batch_geometry(chunks, *, max_neurons=384, max_vertices=1_000_000):
    """Preserve graph order while filling batches across cache chunk boundaries."""
    if (type(max_neurons) is not int or max_neurons < 1
            or type(max_vertices) is not int or max_vertices < 1):
        raise ValueError('Invalid geometry batch bounds')
    pending, count = [], 0
    for chunk in chunks:
        for entry in chunk:
            try:
                vertices = len(entry['geometry'][0])
            except (KeyError, IndexError, TypeError) as exc:
                raise ValueError('Invalid geometry batch entry') from exc
            if vertices < 1 or vertices > max_vertices:
                raise ValueError('Geometry entry exceeds GPU batch bounds')
            if pending and (len(pending) >= max_neurons or count + vertices > max_vertices):
                yield pending
                pending, count = [], 0
            pending.append(entry)
            count += vertices
    if pending:
        yield pending
