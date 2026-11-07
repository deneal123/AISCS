"""Paired per-cell stimulus/control screening for explicit source candidates.

Requires a dedicated NEURON process. This is a model sensitivity screen, not
biological validation and not an exhaustive network response calculation.
"""

from __future__ import annotations

import math
import re
from inspect import signature

import numpy as np

from service.domain.pulse_train import pulse_train
from service.infrastructure.stimulation.point_field import bipolar_potential_mv
from service.infrastructure.stimulation.source_selection import earliest_crossing_source
from service.infrastructure.stimulation.swc_reference import (
    DisconnectedMorphologyError,
    simulate_registered_swc_reference,
    simulate_swc_reference,
)

VIRTUAL_THRESHOLD_GUARD_MV = 1e-6


def _near_threshold(voltage, threshold_mv):
    """Heuristic guard only; it is not a proven global numerical error bound."""
    values = np.asarray(voltage, dtype=float)
    if values.ndim != 2 or not np.isfinite(values).all():
        raise ValueError('Invalid voltage for threshold guard')
    for start in range(0, len(values), 128):
        chunk = values[start:start + 128]
        if np.any((chunk >= threshold_mv - VIRTUAL_THRESHOLD_GUARD_MV)
                  & (chunk <= threshold_mv + VIRTUAL_THRESHOLD_GUARD_MV)):
            return True
    return False


def validate_screen_request(candidates, simulation_parameters, threshold_mv):
    """Reject invalid request-wide settings before creating an output ledger."""
    if (not isinstance(candidates, list) or not candidates
            or any(type(body) is not int or body <= 0 for body in candidates)
            or len(candidates) != len(set(candidates))
            or not isinstance(simulation_parameters, dict)
            or isinstance(threshold_mv, bool) or not isinstance(threshold_mv, int | float)
            or not math.isfinite(threshold_mv)):
        raise ValueError('Invalid source screening request')
    duration = simulation_parameters.get('duration_ms')
    current = simulation_parameters.get('current_na')
    if (isinstance(duration, bool) or not isinstance(duration, int | float)
            or not math.isfinite(duration) or not float(duration).is_integer()
            or not 1 <= duration <= 1000 or isinstance(current, bool)
            or not isinstance(current, int | float) or not math.isfinite(current)
            or current == 0 or 'synaptic_events' in simulation_parameters
            or 'record_membrane_current' in simulation_parameters
            or 'field_coupling' in simulation_parameters):
        raise ValueError('Invalid source screening parameters')
    try:
        bound = signature(simulate_swc_reference).bind('placeholder', **simulation_parameters)
    except TypeError as exc:
        raise ValueError('Incomplete or unknown source screening parameters') from exc
    bound.apply_defaults()
    settings = bound.arguments
    dt = settings['dt_ms']
    nseg = settings['nseg_per_edge']
    membrane = [settings[key] for key in ('axial_resistivity_ohm_cm',
                 'membrane_capacitance_uf_cm2', 'temperature_c', 'initial_voltage_mv')]
    if (isinstance(dt, bool) or not isinstance(dt, int | float) or not math.isfinite(dt)
            or dt <= 0 or abs(round(duration / dt) * dt - duration) > 1e-9
            or type(nseg) is not int or nseg < 1 or nseg % 2 == 0
            or any(isinstance(value, bool) or not isinstance(value, int | float)
                   or not math.isfinite(value) for value in membrane)
            or membrane[0] <= 0 or membrane[1] <= 0 or membrane[2] <= -273.15
            or type(settings['allow_disconnected']) is not bool):
        raise ValueError('Invalid source screening solver settings')
    pulse_train(start_ms=settings['pulse_start_ms'], end_ms=settings['pulse_end_ms'],
                rise_ms=settings['rise_time_ms'], interphase_gap_ms=settings['interphase_gap_ms'],
                shape=settings['pulse_shape'], duration_ms=duration,
                count=settings['pulse_count'], interval_ms=settings['pulse_interval_ms'])
    bipolar_potential_mv(np.empty((0, 3)), simulation_parameters['source_um'],
                         simulation_parameters['return_um'], current,
                         simulation_parameters['conductivity_s_m'],
                         clearance_um=simulation_parameters['clearance_um'])
    return int(duration)


def screen_source_cells(candidates, directories, simulation_parameters, *, threshold_mv,
                        field_coupling='extracellular'):
    """Yield ordered results for all candidates without retaining solver arrays.

    Each cell is solved with the requested pulse and with zero current, keeping
    every other parameter fixed. Cells with a control crossing are marked
    ambiguous; cells with only a stimulated crossing are model candidates.
    Failures remain explicit and must not be treated as negative responses.
    """
    duration = validate_screen_request(candidates, simulation_parameters, threshold_mv)
    if (field_coupling not in ('extracellular', 'virtual_current')
            or (field_coupling == 'virtual_current'
                and simulation_parameters.get('nseg_per_edge', 1) != 1)):
        raise ValueError('Unsupported screening coupling or spatial resolution')
    control_parameters = {**simulation_parameters, 'current_na': 0.0}
    for body in candidates:
        fallback_runs = 0
        try:
            selected = []
            digest = None
            for parameters in (simulation_parameters, control_parameters):
                result, provenance = simulate_registered_swc_reference(
                    body, directories, **parameters, record_membrane_current=False,
                    **({'field_coupling': field_coupling}
                       if field_coupling != 'extracellular' else {}))
                if str(provenance.get('body_id')) != str(body):
                    raise ValueError('Morphology identity changed')
                if (not isinstance(provenance.get('morphology_sha256'), str)
                        or not re.fullmatch(r'[a-f0-9]{64}', provenance['morphology_sha256'])):
                    raise ValueError('Missing morphology digest')
                # Even when standalone fragment simulation is explicitly enabled,
                # its threshold crossings cannot establish whole-cell output.
                if type(provenance.get('components')) is not int or provenance['components'] < 1:
                    raise ValueError('Missing morphology component count')
                if provenance['components'] != 1:
                    raise DisconnectedMorphologyError('Fragment connectivity is unknown')
                if (field_coupling == 'virtual_current'
                        and _near_threshold(result['voltage_mv'], threshold_mv)):
                    fallback_runs += 1
                    expected = provenance['morphology_sha256']
                    result, provenance = simulate_registered_swc_reference(
                        body, directories, **parameters, record_membrane_current=False,
                        expected_morphology_sha256=expected)
                    if (str(provenance.get('body_id')) != str(body)
                            or provenance.get('morphology_sha256') != expected
                            or type(provenance.get('components')) is not int
                            or provenance['components'] != 1):
                        raise ValueError('Morphology changed during reference fallback')
                if digest is not None and digest != provenance.get('morphology_sha256'):
                    raise ValueError('Morphology changed between paired runs')
                digest = provenance.get('morphology_sha256')
                selection = earliest_crossing_source(
                    result['time_ms'], result['voltage_mv'], result['edge_node_ids'],
                    threshold_mv=threshold_mv, duration_ms=int(duration))
                selected.append(selection)
                del result
        except FileNotFoundError:
            yield {'body_id': body, 'status': 'source_missing', **(
                {'fallback_runs': fallback_runs} if field_coupling == 'virtual_current' else {})}
            continue
        except DisconnectedMorphologyError:
            yield {'body_id': body, 'status': 'disconnected_morphology', **(
                {'fallback_runs': fallback_runs} if field_coupling == 'virtual_current' else {})}
            continue
        except ValueError:
            yield {'body_id': body, 'status': 'invalid_or_ambiguous', **(
                {'fallback_runs': fallback_runs} if field_coupling == 'virtual_current' else {})}
            continue
        stimulated, control = selected
        if control is not None:
            yield {'body_id': body, 'status': 'control_crossing', 'morphology_sha256': digest, **(
                {'fallback_runs': fallback_runs} if field_coupling == 'virtual_current' else {})}
        elif stimulated is None:
            yield {'body_id': body, 'status': 'no_crossing', 'morphology_sha256': digest, **(
                {'fallback_runs': fallback_runs} if field_coupling == 'virtual_current' else {})}
        else:
            fallback_metadata = ({'fallback_runs': fallback_runs}
                                 if field_coupling == 'virtual_current' else {})
            yield {'body_id': body, 'status': 'stimulus_only_crossing',
                   'morphology_sha256': digest, 'selection': stimulated, **fallback_metadata}
