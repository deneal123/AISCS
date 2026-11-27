"""An episode says which behaviour the legs were running, and the dataset row carries it."""

from __future__ import annotations

from service.infrastructure.body.dataset import label
from service.infrastructure.body.episode import Episode


def _record(behaviour):
    record = Episode(seed=1, site_um=(0.0, 0.0, 500.0), current_na=-3600.0,
                     source_cells=[1, 2, 3], duration_ms=120, reason="test")
    record.record_body(start=(0.0, 0.0, 0.0), end=(0.01, 0.0, 0.0), curl_start=0.0,
                       curl_end=0.1, escape_latency_ms=None, peak_height_cm=0.01,
                       min_height_cm=0.0, behaviour=behaviour)
    return record


def test_an_episode_records_the_behaviour_it_ran():
    record = _record("groom")
    assert record.body["behaviour"] == "groom"
    assert label(record.record())["behaviour"] == "groom"


def test_a_walk_is_the_default_only_because_the_caller_said_so():
    # No behaviour passed means no behaviour claimed: a reader must be able to tell
    # a straight run from a run whose programme was never asked for.
    record = _record(None)
    assert record.body["behaviour"] is None
    assert label(record.record())["behaviour"] is None


def test_two_behaviours_are_told_apart_by_the_row_alone():
    walk = label(_record("walk").record())
    groom = label(_record("groom").record())
    assert walk["behaviour"] != groom["behaviour"]

class _Graph:
    """The smallest thing run_episode accepts: an id list. A silent episode never
    touches the network, so no connectome is built for this test."""

    def __init__(self, count=10):
        import numpy as np
        self.ids = np.arange(count, dtype=np.int64)


def test_a_silent_episode_can_be_asked_for_a_behaviour():
    from service.infrastructure.body.experiment import run_episode

    record, control = run_episode(_Graph(), source_cells=None, current_na=0.0,
                                  site_um=(0.0, 0.0, 500.0), duration_ms=5,
                                  behaviour="groom")
    assert control.behaviour.name == "groom"
    assert record.body["behaviour"] == "groom"


def test_a_behaviour_the_body_does_not_have_is_refused_before_the_run():
    from service.infrastructure.body.experiment import run_episode

    try:
        run_episode(_Graph(), source_cells=None, current_na=0.0,
                    site_um=(0.0, 0.0, 500.0), duration_ms=5, behaviour="somersault")
    except ValueError as error:
        assert "somersault" in str(error)
    else:
        raise AssertionError("an unknown behaviour was accepted")

