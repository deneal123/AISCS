from types import SimpleNamespace

import pytest

from service.application.population.runner import run_fragment_population


@pytest.mark.parametrize('partial', [False, True])
def test_recording_and_graph_use_same_active_solutions_and_paired_controls(monkeypatch, partial):
    solves, checked, progress = [], [], []
    active_objects = {}

    def solve(body, _directories, **kwargs):
        solves.append((body, kwargs))
        active = kwargs["current_na"] != 0
        result = {"body": body, "active": active}
        if active:
            active_objects[body] = result
        return result, {"body_id": str(body), "morphology_sha256": "a" * 64}

    def diagnostic(_index, _graph, body, _directories, active, quiet, _proof, _control, **_kwargs):
        assert active is active_objects[body] and quiet["active"] is False
        checked.append(body)
        result = {"body_id": str(body)}
        if partial:
            result['candidates'] = [{'included_in_graph': True, 'centerline_distance_um': 2.1,
                                     'status': 'stimulus_only_crossing',
                                     'stimulated_ticks_ms': [1], 'control_ticks_ms': []}]
        return result

    def record(records, _e1, _ref, *, source_model):
        assert source_model == "pointsource"
        captured = list(records)
        assert [solution is active_objects[solution["body"]] for solution, _ in captured] == [
            True,
            True,
        ]
        return {"cells": len(captured)}

    def network(_graph, diagnostics, **_kwargs):
        assert [row["body_id"] for row in diagnostics] == ["1", "2"]
        if partial:
            assert all(row['candidates'][0]['status'] == 'geometry_unresolved'
                       and row['candidates'][0]['stimulated_ticks_ms'] is None
                       for row in diagnostics)
        assert _kwargs['allow_partial_geometry'] is partial
        return {"network": "checked"}

    module = "service.application.population.runner."
    monkeypatch.setattr(module + "simulate_registered_swc_reference", solve)
    monkeypatch.setattr(
        module + "preflight_outgoing_fragment_geometry",
        lambda *_args, **_kwargs: {"morphology_sha256": "a" * 64},
    )
    monkeypatch.setattr(module + "registered_outgoing_fragment_diagnostics", diagnostic)
    monkeypatch.setattr(module + "fragment_edge_schedule", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(module + "record_independent_cells", record)
    monkeypatch.setattr(module + "run_fragment_population_network", network)
    result = run_fragment_population(
        SimpleNamespace(size=3),
        None,
        [],
        source_ids=[1, 2],
        simulation_parameters={"allow_disconnected": True, "current_na": 10.0, "duration_ms": 10},
        electrode_um=[0, 1, 0],
        reference_um=[0, 2, 0],
        source_model="pointsource",
        threshold_mv=-20.0,
        max_distance_um=2.0,
        seed=1,
        allow_partial_geometry=partial,
        progress=lambda phase, done, total: progress.append((phase, done, total)),
    )
    assert checked == [1, 2] and result["recording"]["cells"] == 2
    assert progress == [('geometry', 1, 2), ('geometry', 2, 2),
                        ('cells', 1, 2), ('cells', 2, 2), ('network', 0, 0)]
    assert [settings["current_na"] for _, settings in solves] == [10.0, 0.0, 10.0, 0.0]
    assert all(
        settings["expected_morphology_sha256"] == "a" * 64
        for _, settings in solves
        if settings["current_na"] == 0
    )
    assert "not a full-network physical recording" in result["coverage"]


def test_incomplete_or_unsafe_population_parameters_fail_before_work():
    settings = {"allow_disconnected": True, "current_na": 10.0, "duration_ms": 10}
    for ids, params in [
        ([], settings),
        ([1, 1], settings),
        ([True], settings),
        ([1], {**settings, "allow_disconnected": False}),
        ([1], {**settings, "synaptic_events": []}),
        ([1], {**settings, "solver_backend": "experimental_coreneuron"}),
    ]:
        with pytest.raises(ValueError):
            run_fragment_population(
                None,
                None,
                [],
                source_ids=ids,
                simulation_parameters=params,
                electrode_um=[0, 1, 0],
                reference_um=[0, 2, 0],
                source_model="pointsource",
                threshold_mv=-20.0,
                max_distance_um=2.0,
                seed=1,
            )


def test_experimental_population_solver_is_explicit_for_active_and_control(monkeypatch):
    calls = []
    module = 'service.application.population.runner.'

    def solve(body, _directories, **settings):
        calls.append(settings)
        return {}, {'body_id': str(body), 'morphology_sha256': 'a' * 64}

    monkeypatch.setattr(module + 'simulate_registered_swc_reference', solve)
    monkeypatch.setattr(module + 'preflight_outgoing_fragment_geometry',
                        lambda *_a, **_k: {'morphology_sha256': 'a' * 64})
    monkeypatch.setattr(module + 'registered_outgoing_fragment_diagnostics',
                        lambda *_a, **_k: {'body_id': '1'})
    monkeypatch.setattr(module + 'fragment_edge_schedule', lambda *_a, **_k: {})
    monkeypatch.setattr(module + 'record_independent_cells',
                        lambda records, *_a, **_k: {'cells': len(list(records))})
    monkeypatch.setattr(module + 'run_fragment_population_network',
                        lambda *_a, **_k: {})
    result = run_fragment_population(
        SimpleNamespace(size=2), None, [], source_ids=[1],
        simulation_parameters={'allow_disconnected': True, 'current_na': 10., 'duration_ms': 10},
        electrode_um=[0, 1, 0], reference_um=[0, 2, 0], source_model='pointsource',
        threshold_mv=-20., max_distance_um=2., seed=1,
        experimental_solver_backend='experimental_coreneuron')
    assert result['experimental_solver_backend'] == 'experimental_coreneuron'
    assert [row['current_na'] for row in calls] == [10., 0.]
    assert all(row['solver_backend'] == 'experimental_coreneuron'
               and row['field_coupling'] == 'experimental_virtual_current' for row in calls)


def test_experimental_cuda_pairs_active_and_control(monkeypatch):
    calls = []
    module = 'service.application.population.runner.'

    def gpu(requests, _directories, parameters, **_kwargs):
        calls.append(parameters['current_na'])
        return [{'id': row['id'], 'arrays': {'current': parameters['current_na']},
                 'provenance': {'body_id': str(row['id']), 'morphology_sha256': 'a' * 64,
                                'experimental_hh_table_clamped': False}}
                for row in requests]

    def diagnostic(_index, _graph, body, _dirs, active, control, *_args, **_kwargs):
        assert active['current'] == 10. and control['current'] == 0.
        return {'body_id': str(body)}

    monkeypatch.setattr('service.application.feedback.gpu_replay.replay_gpu_batch', gpu)
    monkeypatch.setattr(module + 'preflight_outgoing_fragment_geometry',
                        lambda *_a, **_k: {'morphology_sha256': 'a' * 64})
    monkeypatch.setattr(module + 'registered_outgoing_fragment_diagnostics', diagnostic)
    monkeypatch.setattr(module + 'fragment_edge_schedule', lambda *_a, **_k: {})
    monkeypatch.setattr(module + 'record_independent_cells',
                        lambda records, *_a, **_k: {'cells': len(list(records))})
    monkeypatch.setattr(module + 'run_fragment_population_network', lambda *_a, **_k: {})
    result = run_fragment_population(
        SimpleNamespace(size=3), None, [], source_ids=[1, 2],
        simulation_parameters={'allow_disconnected': True, 'current_na': 10., 'duration_ms': 10},
        electrode_um=[0, 1, 0], reference_um=[0, 2, 0], source_model='pointsource',
        threshold_mv=-20., max_distance_um=2., seed=1,
        experimental_solver_backend='experimental_cuda', experimental_gpu_output_budget_bytes=1000)
    assert result['experimental_solver_backend'] == 'experimental_cuda'
    assert result['recording']['cells'] == 2 and calls == [10., 0.]
    assert result['experimental_gpu_table_clamped'] == {'active': [], 'control': []}


def test_unresolved_first_source_stops_before_solving_later_cells(monkeypatch):
    solved = []

    def solve(body, _directories, **kwargs):
        solved.append((body, kwargs["current_na"]))
        return {}, {"body_id": str(body), "morphology_sha256": "a" * 64}

    def reject(*_args, **_kwargs):
        raise ValueError("Unresolved geometric candidate: source 1")

    module = "service.application.population.runner."
    monkeypatch.setattr(module + "simulate_registered_swc_reference", solve)
    monkeypatch.setattr(
        module + "preflight_outgoing_fragment_geometry",
        lambda *_args, **_kwargs: {"morphology_sha256": "a" * 64},
    )
    monkeypatch.setattr(module + "registered_outgoing_fragment_diagnostics", lambda *_a, **_kw: {})
    monkeypatch.setattr(module + "fragment_edge_schedule", reject)
    monkeypatch.setattr(
        module + "record_independent_cells", lambda records, *_a, **_kw: list(records)
    )
    with pytest.raises(ValueError, match="source 1"):
        run_fragment_population(
            None,
            None,
            [],
            source_ids=[1, 2],
            simulation_parameters={
                "allow_disconnected": True,
                "current_na": 10.0,
                "duration_ms": 10,
            },
            electrode_um=[0, 1, 0],
            reference_um=[0, 2, 0],
            source_model="pointsource",
            threshold_mv=-20.0,
            max_distance_um=2.0,
            seed=1,
        )
    assert solved == [(1, 10.0), (1, 0.0)]


def test_unresolved_geometry_in_later_source_stops_before_any_solves(monkeypatch):
    checked, solved = [], []

    def preflight(_index, _graph, body, _directories, **_kwargs):
        checked.append(body)
        if body == 2:
            raise ValueError("Unresolved geometric candidate: source 2")
        return {"morphology_sha256": "a" * 64}

    module = "service.application.population.runner."
    monkeypatch.setattr(module + "preflight_outgoing_fragment_geometry", preflight)
    monkeypatch.setattr(
        module + "simulate_registered_swc_reference", lambda body, *_a, **_kw: solved.append(body)
    )
    with pytest.raises(ValueError, match="source 2"):
        run_fragment_population(
            None,
            None,
            [],
            source_ids=[1, 2],
            simulation_parameters={
                "allow_disconnected": True,
                "current_na": 10.0,
                "duration_ms": 10,
            },
            electrode_um=[0, 1, 0],
            reference_um=[0, 2, 0],
            source_model="pointsource",
            threshold_mv=-20.0,
            max_distance_um=2.0,
            seed=1,
        )
    assert checked == [1, 2]
    assert solved == []


def test_reports_multiple_geometry_failures_before_any_solves(monkeypatch):
    checked, solved = [], []

    def preflight(_index, _graph, body, _directories, **_kwargs):
        checked.append(body)
        if body in (2, 3):
            raise ValueError(f'Unresolved geometric candidate: source {body}, '
                             '2/1199 graph synapses outside 2 um; maximum 2.12 um')
        return {'morphology_sha256': 'a' * 64}

    module = 'service.application.population.runner.'
    monkeypatch.setattr(module + 'preflight_outgoing_fragment_geometry', preflight)
    monkeypatch.setattr(
        module + 'simulate_registered_swc_reference', lambda *a, **kw: solved.append(a)
    )
    with pytest.raises(ValueError, match=r'2:2:1199,3:2:1199; omitted:0'):
        run_fragment_population(
            None, None, [], source_ids=[1, 2, 3],
            simulation_parameters={'allow_disconnected': True, 'current_na': 10.0,
                                   'duration_ms': 10},
            electrode_um=[0, 1, 0], reference_um=[0, 2, 0], source_model='pointsource',
            threshold_mv=-20.0, max_distance_um=2.0, seed=1,
        )
    assert checked == [1, 2, 3]
    assert solved == []


def test_reports_more_than_five_geometric_failures_with_bounded_message(monkeypatch):
    def preflight(_index, _graph, body, _directories, **_kwargs):
        raise ValueError(f'Unresolved geometric candidate: source {body}, '
                         '2/1199 graph synapses outside 2 um; maximum 2.12 um')

    monkeypatch.setattr('service.application.population.runner.preflight_outgoing_fragment_geometry',
                        preflight)
    with pytest.raises(ValueError) as error:
        run_fragment_population(
            None, None, [], source_ids=list(range(1, 13)),
            simulation_parameters={'allow_disconnected': True, 'current_na': 10.0,
                                   'duration_ms': 10},
            electrode_um=[0, 1, 0], reference_um=[0, 2, 0], source_model='pointsource',
            threshold_mv=-20.0, max_distance_um=2.0, seed=1,
        )
    assert '12:2:1199; omitted:0' in str(error.value)
    assert len(str(error.value)) < 500
