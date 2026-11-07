"""Map known executor failures to safe, user-facing diagnostic codes."""

import re

_CONTACT_ERRORS = frozenset({
    "Observation point intersects a contact exclusion sphere",
    "Contact exclusion sphere intersects a cable segment",
    "Contact exclusion sphere intersects a degenerate cable segment",
    "Contact exclusion sphere intersects an isolated SWC vertex",
})


def feedback_failure_diagnostics(status: dict, configuration: dict):
    """Accept only bounded counters for an identified, non-converged calculation."""
    code = executor_failure_code(status)
    expected = {'executor_feedback_iteration_limit': 'iteration_limit',
                'executor_feedback_cycle': 'cycle_detected'}.get(code)
    detail = status.get('error', {}) if isinstance(status, dict) else {}
    diagnostics = detail.get('feedback_diagnostics') if isinstance(detail, dict) else None
    maximum = configuration.get('max_iterations') if isinstance(configuration, dict) else None
    if (expected is None or type(maximum) is not int or not 1 <= maximum <= 100
            or not isinstance(diagnostics, dict) or set(diagnostics) != {'status', 'history'}
            or diagnostics['status'] != expected or not isinstance(diagnostics['history'], list)
            or not 1 <= len(diagnostics['history']) <= maximum):
        return None
    fields = {'iteration', 'input_events', 'unresolved_events', 'outside_window',
              'output_edge_records', 'network_spikes'}
    for position, row in enumerate(diagnostics['history'], 1):
        if (not isinstance(row, dict) or set(row) != fields or row.get('iteration') != position
                or any(type(row[key]) is not int or not 0 <= row[key] <= 1_000_000_000
                       for key in fields)):
            return None
    return diagnostics


def executor_failure_code(status: dict) -> str:
    """Do not expose exception text, paths or unknown internal diagnostics."""
    if not isinstance(status, dict):
        return "executor_failed"
    state = status.get("status")
    detail = status.get("error")
    if (state == 'failed' and isinstance(detail, dict) and detail.get('type') == 'ValueError'
            and isinstance(detail.get('message'), str) and detail['message'] in {
                'field_source_missing', 'field_contact_exclusion', 'field_invalid_geometry',
                'field_partial_geometry', 'field_missing_curvature',
            }):
        return 'executor_' + detail['message']
    if (state == "failed" and isinstance(detail, dict) and detail.get("type") == "ValueError"
            and detail.get("message") == "Synapse at zero-area section endpoint is unsupported"):
        return "executor_synapse_endpoint"
    if (state == "failed" and isinstance(detail, dict) and detail.get("type") == "ValueError"
            and isinstance(detail.get("message"), str) and detail["message"] in {
                "Coupled feedback did not converge: iteration_limit",
                "Coupled feedback did not converge: cycle_detected"}):
        return ("executor_feedback_iteration_limit" if detail["message"].endswith("iteration_limit")
                else "executor_feedback_cycle")
    if (state == "failed" and isinstance(detail, dict) and detail.get("type") == "ValueError"
            and isinstance(detail.get("message"), str) and detail["message"] in _CONTACT_ERRORS):
        return "executor_contact_clearance"
    if (state == "failed" and isinstance(detail, dict) and detail.get("type") == "ValueError"
            and isinstance(detail.get("message"), str) and re.fullmatch(
                r"Contact clearance not established: [1-9][0-9]* potential SWC intersections "
                r"\((?:STIM\+|STIM−|E1|REF)=[1-9][0-9]*"
                r"(?:, (?:STIM\+|STIM−|E1|REF)=[1-9][0-9]*)*\)",
                detail["message"])):
        return "executor_contact_clearance"
    if (state == "failed" and isinstance(detail, dict) and detail.get("type") == "ValueError"
            and detail.get("message") == "Verified contact-screen indexes are unavailable"):
        return "executor_contact_screen_unavailable"
    if (state == "failed" and isinstance(detail, dict) and detail.get("type") == "ValueError"
            and isinstance(detail.get("message"), str)
            and detail["message"].startswith("Unresolved geometric candidates:")):
        match = re.fullmatch(
            r"Unresolved geometric candidates: ([1-9][0-9]{0,18}:[1-9][0-9]{0,8}:"
            r"[1-9][0-9]{0,8}(?:,[1-9][0-9]{0,18}:[1-9][0-9]{0,8}:"
            r"[1-9][0-9]{0,8}){1,255}); omitted:([0-9]{1,3})",
            detail["message"],
        )
        if match:
            triples = [tuple(map(int, part.split(':'))) for part in match[1].split(',')]
            omitted = int(match[2])
            if (all(body < 2**63 and count <= total for body, count, total in triples)
                    and len({item[0] for item in triples}) == len(triples)
                    and len(triples) + omitted <= 256 and len(match[1]) <= 400):
                return f'executor_synapse_geometries:{match[1]};omitted:{omitted}'
        return "executor_synapse_geometry"
    if (state == "failed" and isinstance(detail, dict) and detail.get("type") == "ValueError"
            and isinstance(detail.get("message"), str)
            and detail["message"].startswith("Unresolved geometric candidate:")):
        match = re.fullmatch(
            r"Unresolved geometric candidate: source ([1-9][0-9]{0,18}), "
            r"([1-9][0-9]*)/([1-9][0-9]*) graph synapses outside "
            r"[0-9.eE+-]+ um; maximum [0-9.eE+-]+ um",
            detail["message"],
        )
        if match and int(match[1]) < 2**63 and int(match[2]) <= int(match[3]):
            return f"executor_synapse_geometry:{match[1]}:{match[2]}:{match[3]}"
        return "executor_synapse_geometry"
    if (state == "failed" and isinstance(detail, dict) and detail.get("type") == "ValueError"
            and detail.get("message") == "Source morphology digest mismatch"):
        return "executor_morphology_changed"
    return ("executor_" + state if isinstance(state, str)
            and state in {"failed", "cancelled", "interrupted"} else "executor_failed")
