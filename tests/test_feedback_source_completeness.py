from types import SimpleNamespace

import pytest

from service.application.feedback.schedule import build_feedback_schedule_from_archives


def test_silent_unresolved_source_is_not_published_as_complete(monkeypatch):
    monkeypatch.setattr('service.application.feedback.event_archive.iter_aligned_archive_batches',
                        lambda *_a, **_k: iter([None]))
    monkeypatch.setattr('service.application.feedback.direct_events.iter_verified_source_feedback',
        lambda *_a, **_k: iter([{'events': [], 'diagnostics': {10: {'candidates': [{
            'included_in_graph': True, 'status': 'geometry_unresolved'}]}}}]))
    graph = SimpleNamespace(provenance={'manifest_sha256': 'a' * 64})
    with pytest.raises(ValueError, match='Unresolved source geometry'):
        build_feedback_schedule_from_archives(graph, [10], None, [], {},
            active_path='unused', active_sha256='b' * 64, control_path='unused2',
            control_sha256='c' * 64, diagnostics_factory=lambda _: {},
            morphology_sha256={10: 'd' * 64}, duration_ms=10, max_events=10,
            max_source_distance_um=2., max_target_distance_um=2.)
