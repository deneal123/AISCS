import pytest

from service.services.simulations.failure_codes import (
    executor_failure_code,
    feedback_failure_diagnostics,
)


@pytest.mark.parametrize(('reason', 'code'), [
    ('iteration_limit', 'executor_feedback_iteration_limit'),
    ('cycle_detected', 'executor_feedback_cycle'),
])
def test_maps_exact_feedback_convergence_failure(reason, code):
    detail = {'status': 'failed', 'error': {'type': 'ValueError',
        'message': f'Coupled feedback did not converge: {reason}'}}
    assert executor_failure_code(detail) == code
    detail['error']['message'] += ' arbitrary details'
    assert executor_failure_code(detail) == 'executor_failed'


def test_maps_only_the_exact_unsupported_synapse_endpoint_error():
    status = {'status': 'failed', 'error': {'type': 'ValueError',
        'message': 'Synapse at zero-area section endpoint is unsupported'}}
    assert executor_failure_code(status) == 'executor_synapse_endpoint'
    status['error']['message'] += ' unrelated details'
    assert executor_failure_code(status) == 'executor_failed'


def test_feedback_diagnostics_accept_only_bounded_matching_counters():
    row = {'iteration': 1, 'input_events': 2, 'unresolved_events': 0, 'outside_window': 0,
           'output_edge_records': 1, 'network_spikes': 0}
    diagnostic = {'status': 'iteration_limit', 'history': [row]}
    status = {'status': 'failed', 'error': {'type': 'ValueError',
        'message': 'Coupled feedback did not converge: iteration_limit',
        'feedback_diagnostics': diagnostic}}
    assert feedback_failure_diagnostics(status, {'max_iterations': 6}) == diagnostic
    assert feedback_failure_diagnostics(status, {'max_iterations': 0}) is None
    status['error']['feedback_diagnostics'] = {'status': 'iteration_limit',
        'history': [{**row, 'network_spikes': -1}]}
    assert feedback_failure_diagnostics(status, {'max_iterations': 6}) is None
    status['error']['feedback_diagnostics'] = {'status': 'cycle_detected', 'history': [row]}
    assert feedback_failure_diagnostics(status, {'max_iterations': 6}) is None


@pytest.mark.parametrize("message", [
    "Observation point intersects a contact exclusion sphere",
    "Contact exclusion sphere intersects a cable segment",
    "Contact exclusion sphere intersects a degenerate cable segment",
    "Contact exclusion sphere intersects an isolated SWC vertex",
    "Contact clearance not established: 29 potential SWC intersections (STIM+=29, E1=2)",
])
def test_maps_known_contact_failures(message):
    assert executor_failure_code({"status": "failed", "error": {
        "type": "ValueError", "message": message}}) == "executor_contact_clearance"


def test_maps_exact_morphology_digest_mismatch_without_exposing_details():
    assert executor_failure_code({"status": "failed", "error": {
        "type": "ValueError", "message": "Source morphology digest mismatch"}}) == (
            "executor_morphology_changed")
    assert executor_failure_code({"status": "failed", "error": {
        "type": "ValueError", "message": "Source morphology digest mismatch: /private"}}) == (
            "executor_failed")


def test_maps_missing_screen_indexes_without_exposing_internal_details():
    status = {"status": "failed", "error": {
        "type": "ValueError", "message": "Verified contact-screen indexes are unavailable"}}
    assert executor_failure_code(status) == "executor_contact_screen_unavailable"
    status["error"]["message"] += ": /private"
    assert executor_failure_code(status) == "executor_failed"


def test_maps_unresolved_synapse_geometry_without_exposing_details():
    status = {"status": "failed", "error": {"type": "ValueError",
              "message": "Unresolved geometric candidate: 1/10055 graph synapses outside 2 um"}}
    assert executor_failure_code(status) == "executor_synapse_geometry"
    status["error"]["message"] = (
        "Unresolved geometric candidate: source 512731, 2/1199 graph synapses "
        "outside 2 um; maximum 2.11748 um"
    )
    assert executor_failure_code(status) == "executor_synapse_geometry:512731:2:1199"
    status["error"]["message"] += " /private"
    assert executor_failure_code(status) == "executor_synapse_geometry"
    status["error"]["message"] = "/private/other failure"
    assert executor_failure_code(status) == "executor_failed"


def test_maps_bounded_multiple_geometric_failures():
    status = {'status': 'failed', 'error': {'type': 'ValueError', 'message':
        'Unresolved geometric candidates: 19084:2:1199,13133:22:2772; omitted:0'}}
    assert executor_failure_code(status) == (
        'executor_synapse_geometries:19084:2:1199,13133:22:2772;omitted:0'
    )
    status['error']['message'] = (
        'Unresolved geometric candidates: 19084:1200:1199,13133:22:2772; omitted:0'
    )
    assert executor_failure_code(status) == 'executor_synapse_geometry'


def test_maps_more_than_five_geometric_failures_within_storage_bound():
    items = ','.join(f'{body}:1:100' for body in range(1, 10))
    status = {'status': 'failed', 'error': {'type': 'ValueError', 'message':
              f'Unresolved geometric candidates: {items}; omitted:0'}}
    assert executor_failure_code(status) == f'executor_synapse_geometries:{items};omitted:0'
    items = ','.join(f'{body}:1:100' for body in range(1, 65))
    status['error']['message'] = f'Unresolved geometric candidates: {items}; omitted:0'
    assert executor_failure_code(status) == 'executor_synapse_geometry'
    status['error']['message'] = (
        'Unresolved geometric candidates: 19084:2:1199,19084:1:1199; omitted:0'
    )
    assert executor_failure_code(status) == 'executor_synapse_geometry'
    status['error']['message'] = (
        'Unresolved geometric candidates: 19084:2:1199,13133:22:2772; omitted:999'
    )
    assert executor_failure_code(status) == 'executor_synapse_geometry'


@pytest.mark.parametrize("status", [None, {}, {"status": []}, {"status": "failed", "error": {
    "type": "ValueError", "message": []}}, {"status": "failed", "error": {
    "type": "RuntimeError", "message": "/secret/path"}}])
def test_unknown_or_malformed_failures_do_not_leak(status):
    assert executor_failure_code(status) == "executor_failed"
