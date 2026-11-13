"""Isolated NEURON benchmark on source SWC geometry.

HH defaults are an engineering reference, not fitted Drosophila properties.
The extracellular field is an infinite homogeneous-medium point-source model.
Run in a dedicated process: NEURON state and clock are process-global.
"""

from __future__ import annotations

import hashlib
import json
import math

import numpy as np

from service.infrastructure.connectome.morphology import neurite_landmark
from service.infrastructure.stimulation.point_field import (
    bipolar_potential_mv,
    validate_segment_clearance,
)


class DisconnectedMorphologyError(ValueError):
    """The source contains multiple fragments with unknown connections."""


def _event_digest(events):
    """Bind the ordered event list to the numerical solution."""
    try:
        payload = json.dumps(events or [], sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid synaptic event provenance") from exc
    return np.frombuffer(hashlib.sha256(payload).digest(), dtype=np.uint8).copy()


def simulate_swc_reference(
    swc: str,
    source_um,
    return_um,
    current_na,
    conductivity_s_m,
    *,
    clearance_um,
    dt_ms=0.025,
    duration_ms=10.0,
    pulse_start_ms=2.0,
    pulse_end_ms=3.0,
    rise_time_ms=0.0,
    pulse_shape="monophasic",
    interphase_gap_ms=0.0,
    pulse_count=1,
    pulse_interval_ms=None,
    nseg_per_edge=1,
    nseg_by_edge=None,
    axial_resistivity_ohm_cm=100.0,
    membrane_capacitance_uf_cm2=1.0,
    temperature_c=23.0,
    initial_voltage_mv=-65.0,
    allow_disconnected=False,
    synaptic_events=None,
    record_membrane_current=True,
    field_coupling="extracellular",
    integration_order=0,
    solver_backend="neuron",
    experimental_hh_direct=False,
):
    """Calculate membrane currents for each SWC edge; no network coupling is inferred.

    Integration order 2 is experimental: recorded currents may have different
    temporal alignment, so it is not enabled by the population contract.
    """
    from neuron import h

    morphology = neurite_landmark(swc)
    if type(allow_disconnected) is not bool:
        raise ValueError("allow_disconnected must be boolean")
    if type(record_membrane_current) is not bool:
        raise ValueError("record_membrane_current must be boolean")
    if type(experimental_hh_direct) is not bool:
        raise ValueError("experimental_hh_direct must be boolean")
    if type(integration_order) is not int or integration_order not in (0, 2):
        raise ValueError("Unsupported NEURON integration order")
    if field_coupling not in ("extracellular", "virtual_current", "experimental_virtual_current"):
        raise ValueError("Unsupported field coupling")
    if solver_backend not in ("neuron", "experimental_coreneuron"):
        raise ValueError("Unsupported solver backend")
    if solver_backend == "experimental_coreneuron" and (
            field_coupling != "experimental_virtual_current" or integration_order != 0
            or experimental_hh_direct):
        raise ValueError("CoreNEURON requires experimental virtual current and fixed integration")
    if field_coupling == "virtual_current" and (record_membrane_current
            or nseg_per_edge != 1 or nseg_by_edge not in (None, {})
            or synaptic_events not in (None, [])):
        raise ValueError("Virtual-current screening requires one segment and no current recording")
    if morphology["components"] != 1 and not allow_disconnected:
        raise DisconnectedMorphologyError("Reference neuron requires one connected SWC component")
    from service.domain.pulse_train import pulse_train

    try:
        pulse_times, pulse_fractions = pulse_train(
            start_ms=pulse_start_ms, end_ms=pulse_end_ms, rise_ms=rise_time_ms,
            interphase_gap_ms=interphase_gap_ms, shape=pulse_shape, duration_ms=duration_ms,
            count=pulse_count, interval_ms=pulse_interval_ms)
    except ValueError as exc:
        raise ValueError('Invalid reference timing') from exc
    scalars = (dt_ms, duration_ms, pulse_start_ms, pulse_end_ms, rise_time_ms, interphase_gap_ms)
    if (
        any(isinstance(value, bool | np.bool_) or not math.isfinite(value) for value in scalars)
        or dt_ms <= 0
        or not 0 < pulse_start_ms < pulse_end_ms < duration_ms
        or rise_time_ms < 0 or 2 * rise_time_ms > pulse_end_ms - pulse_start_ms
        or pulse_shape not in ("monophasic", "biphasic") or interphase_gap_ms < 0
        or (pulse_shape == "monophasic" and interphase_gap_ms != 0)
        or (pulse_shape == "biphasic"
            and pulse_end_ms + interphase_gap_ms + pulse_end_ms - pulse_start_ms >= duration_ms)
        or abs(round(duration_ms / dt_ms) * dt_ms - duration_ms) > 1e-9
    ):
        raise ValueError("Invalid reference timing")
    if type(nseg_per_edge) is not int or nseg_per_edge < 1 or nseg_per_edge % 2 == 0:
        raise ValueError("Segments per edge must be a positive odd integer")
    membrane_parameters = (axial_resistivity_ohm_cm, membrane_capacitance_uf_cm2,
                           temperature_c, initial_voltage_mv)
    if (any(isinstance(value, bool | np.bool_) or not math.isfinite(value)
            for value in membrane_parameters) or axial_resistivity_ohm_cm <= 0
            or membrane_capacitance_uf_cm2 <= 0 or temperature_c <= -273.15):
        raise ValueError("Invalid membrane parameters")
    if any(True for _ in h.allsec()):
        raise RuntimeError("Reference solver requires a dedicated NEURON process")
    rows = [
        row.split() for row in swc.splitlines() if row.strip() and not row.lstrip().startswith("#")
    ]
    nodes = {
        int(row[0]): (
            np.asarray([float(x) * 0.008 for x in row[2:5]]),
            float(row[5]) * 0.008,
            int(row[6]),
        )
        for row in rows
    }
    edges = [(node, parent) for node, (_, _, parent) in nodes.items() if parent != -1]
    if nseg_by_edge is None:
        nseg_by_edge = {}
    if not isinstance(nseg_by_edge, dict):
        raise ValueError("Invalid per-edge segment counts")
    overrides = {}
    for node, count in nseg_by_edge.items():
        if type(node) is str and node.isascii() and node.isdigit() and str(int(node)) == node:
            node = int(node)
        if (type(node) is not int or node <= 0 or node in overrides or type(count) is not int
                or count < 1 or count % 2 == 0):
            raise ValueError("Invalid per-edge segment counts")
        overrides[node] = count
    if not set(overrides).issubset({node for node, _ in edges}):
        raise ValueError("Invalid per-edge segment counts")
    counts = {node: overrides.get(node, nseg_per_edge) for node, _ in edges}
    roots = {node for node, (_, _, parent) in nodes.items() if parent == -1}
    if not roots.issubset({parent for _, parent in edges}):
        raise ValueError("Reference cannot represent isolated SWC roots")
    if not edges or any(
        nodes[node][1] <= 0
        or nodes[parent][1] <= 0
        or np.linalg.norm(nodes[node][0] - nodes[parent][0]) <= 0
        for node, parent in edges
    ):
        raise ValueError("Reference requires nonzero edge lengths and radii")
    event_fields = {"child_node_id", "position", "time_ms", "weight_us", "tau1_ms", "tau2_ms",
                    "reversal_mv"}
    if synaptic_events is None:
        synaptic_events = []
    if not isinstance(synaptic_events, list):
        raise ValueError("Invalid synaptic event list")
    edge_nodes = {node for node, _ in edges}
    for event in synaptic_events:
        if (not isinstance(event, dict) or set(event) != event_fields
                or type(event["child_node_id"]) is not int
                or event["child_node_id"] not in edge_nodes):
            raise ValueError("Invalid synaptic event location")
        values = [event[key] for key in event_fields if key != "child_node_id"]
        if (any(isinstance(value, bool | np.bool_) or not isinstance(value, int | float)
                or not math.isfinite(value) for value in values)
                or not 0 <= event["position"] <= 1 or not 0 < event["time_ms"] < duration_ms
                or event["weight_us"] <= 0 or not 0 < event["tau1_ms"] < event["tau2_ms"]
                or not 1e-9 <= event["tau1_ms"] / event["tau2_ms"] <= .9999):
            raise ValueError("Invalid synaptic event parameters")
        # Zero-area end nodes behave differently when NEURON's extracellular
        # mechanism is inserted, including in the recorded membrane current.
        # Do not silently move the source position or publish that result.
        if event["position"] in (0, 1):
            raise ValueError("Synapse at zero-area section endpoint is unsupported")
    midpoints = np.asarray(
        [
            nodes[parent][0] + fraction * (nodes[node][0] - nodes[parent][0])
            for node, parent in edges
            for fraction in (np.arange(counts[node]) + 0.5) / counts[node]
        ]
    )
    starts = np.asarray(
        [
            nodes[parent][0] + (segment / counts[node]) * (nodes[node][0] - nodes[parent][0])
            for node, parent in edges
            for segment in range(counts[node])
        ]
    )
    ends = np.asarray(
        [
            nodes[parent][0] + ((segment + 1) / counts[node]) * (nodes[node][0] - nodes[parent][0])
            for node, parent in edges
            for segment in range(counts[node])
        ]
    )
    diameters = np.asarray(
        [
            2 * (nodes[parent][1] + fraction * (nodes[node][1] - nodes[parent][1]))
            for node, parent in edges
            for fraction in (np.arange(counts[node]) + 0.5) / counts[node]
        ]
    )
    endpoint_radii = np.asarray(
        [
            [nodes[parent][1] + fraction * (nodes[node][1] - nodes[parent][1])
             for fraction in (segment / counts[node], (segment + 1) / counts[node])]
            for node, parent in edges
            for segment in range(counts[node])
        ]
    )
    validate_segment_clearance(
        np.asarray([nodes[parent][0] for node, parent in edges]),
        np.asarray([nodes[node][0] for node, parent in edges]),
        [source_um, return_um], clearance_um,
        np.asarray([[nodes[parent][1], nodes[node][1]] for node, parent in edges]),
    )
    field = bipolar_potential_mv(
        midpoints, source_um, return_um, current_na, conductivity_s_m, clearance_um=clearance_um
    )
    h.load_file("stdrun.hoc")
    h.CVode().active(0)
    h.CVode().use_fast_imem(1)
    sections, vectors, synapses, event_connections, clamps = {}, [], [], [], []
    voltage, current, recorded_time, recorded_stimulus = [], None, None, None
    core = parallel_context = detector = None
    previous_cache_efficient = None
    previous_hh_usetable = None
    try:
        for node, parent in edges:
            section = h.Section(name=f"aiscs_swc_{node}")
            sections[node] = section
            section.Ra = axial_resistivity_ohm_cm
            section.cm = membrane_capacitance_uf_cm2
            section.nseg = counts[node]
            section.insert("hh")
            if field_coupling == "extracellular":
                section.insert("extracellular")
            h.pt3dclear(sec=section)
            for point, radius in (nodes[parent][:2], nodes[node][:2]):
                h.pt3dadd(*point, 2 * radius, sec=section)
        root_anchor = {}
        for node, parent in edges:
            if parent in sections:
                sections[node].connect(sections[parent](1), 0)
            elif parent in root_anchor:
                sections[node].connect(sections[root_anchor[parent]](0), 0)
            else:
                root_anchor[parent] = node
        for event in synaptic_events:
            synapse = h.Exp2Syn(sections[event["child_node_id"]](event["position"]))
            synapse.tau1, synapse.tau2 = event["tau1_ms"], event["tau2_ms"]
            synapse.e = event["reversal_mv"]
            connection = h.NetCon(None, synapse)
            connection.weight[0] = event["weight_us"]
            synapses.append(synapse)
            event_connections.append(connection)
        times = h.Vector(pulse_times)
        segments = [segment for node, _ in edges for segment in sections[node]]
        if field_coupling in ("virtual_current", "experimental_virtual_current"):
            from service.infrastructure.stimulation.virtual_current import (
                adaptive_junctions,
                junction_currents,
            )

            h.define_shape()
            junctions = adaptive_junctions(edges, counts, sections, segments)
            coupling_values = junction_currents(field, junctions)
            for segment, value in zip(segments, coupling_values, strict=True):
                clamp = h.IClamp(segment)
                clamp.delay, clamp.dur = 0, duration_ms + 1
                waveform = h.Vector([value * fraction for fraction in pulse_fractions])
                waveform.play(clamp._ref_amp, times, 1)
                vectors.append(waveform)
                clamps.append(clamp)
        elif np.any(field):
            for segment, value in zip(segments, field, strict=True):
                waveform = h.Vector([value * fraction for fraction in pulse_fractions])
                waveform.play(segment._ref_e_extracellular, times, 1)
                vectors.append(waveform)
        else:
            # A zero-current control has no time-varying extracellular drive.
            # Avoid thousands of identical play vectors, but set the potential
            # explicitly so a previous NEURON run cannot affect this control.
            for segment in segments:
                segment.e_extracellular = 0.0
        recorded_time = h.Vector().record(h._ref_t)
        voltage = [h.Vector().record(segment._ref_v) for segment in segments]
        current = ([h.Vector().record(segment._ref_i_membrane_) for segment in segments]
                   if record_membrane_current else None)
        if solver_backend == "neuron":
            stimulus_reference = h.ref(0.0)
            stimulus_waveform = h.Vector(pulse_fractions)
            stimulus_waveform.play(stimulus_reference, times, 1)
            vectors.append(stimulus_waveform)
            recorded_stimulus = h.Vector().record(stimulus_reference)
        else:
            from neuron import coreneuron

            if coreneuron.enable or coreneuron.gpu:
                raise RuntimeError("CoreNEURON must be disabled and configured for CPU")
            parallel_context = h.ParallelContext()
            if parallel_context.nhost() != 1 or parallel_context.gid_exists(0):
                raise RuntimeError("CoreNEURON requires an isolated single-process context")
            parallel_context.set_gid2node(0, parallel_context.id())
            anchor = next(iter(sections.values()))
            detector = h.NetCon(anchor(0.5)._ref_v, None, sec=anchor)
            parallel_context.cell(0, detector)
            previous_cache_efficient = h.CVode().cache_efficient()
            h.CVode().cache_efficient(1)
            core = coreneuron
            core.enable = True
        # NEURON integration settings are process-global and may survive a
        # previous independent cell; fix the documented numerical mode explicitly.
        previous_hh_usetable = float(h.usetable_hh)
        h.usetable_hh = 0 if experimental_hh_direct else 1
        h.secondorder = integration_order
        h.dt, h.steps_per_ms, h.celsius = dt_ms, 1 / dt_ms, temperature_c
        h.finitialize(initial_voltage_mv)
        for event, connection in zip(synaptic_events, event_connections, strict=True):
            connection.event(event["time_ms"])
        # Keep fixed-step integration in NEURON instead of crossing the
        # Python/HOC boundary for each individual step.
        if core is None:
            h.continuerun(duration_ms)
        else:
            parallel_context.psolve(duration_ms)
        result = {
            "time_ms": np.asarray(recorded_time).copy(),
            "edge_node_ids": np.asarray([node for node, _ in edges for _ in range(counts[node])]),
            "midpoints_um": midpoints,
            "starts_um": starts,
            "ends_um": ends,
            "diameters_um": diameters,
            "endpoint_radii_um": endpoint_radii,
            "field_mv": field,
            "stimulation_parameters": np.asarray(
                [*source_um, *return_um, current_na, conductivity_s_m, clearance_um,
                 pulse_start_ms, pulse_end_ms, rise_time_ms, interphase_gap_ms,
                 1 if pulse_shape == "biphasic" else 0,
                 *([pulse_count, pulse_interval_ms] if pulse_count > 1 else [])], dtype=float
            ),
            "stimulus_fraction": (np.asarray(recorded_stimulus).copy() if core is None else
                                  np.interp(np.asarray(recorded_time), pulse_times,
                                            pulse_fractions)),
            "synaptic_events_sha256": _event_digest(synaptic_events),
            "voltage_mv": np.asarray([np.asarray(row).copy() for row in voltage]),
        }
        if current is not None:
            result["membrane_current_na"] = np.asarray([np.asarray(row).copy() for row in current])
        if not all(np.isfinite(value).all() for value in result.values()):
            raise ValueError("Non-finite reference solution")
        return result
    finally:
        if core is not None:
            core.enable = False
        if previous_cache_efficient is not None:
            h.CVode().cache_efficient(previous_cache_efficient)
        if previous_hh_usetable is not None:
            h.usetable_hh = previous_hh_usetable
        # Each play_remove searches NEURON's play/record registry. Release
        # recording vectors first so the search does not repeatedly traverse
        # thousands of finished recorders. Result arrays above are copied.
        voltage.clear()
        if current is not None:
            current.clear()
        recorded_time = None
        recorded_stimulus = None
        for waveform in vectors:
            waveform.play_remove()
        for section in sections.values():
            h.delete_section(sec=section)


def record_swc_reference(
    result: dict, electrode_um, reference_um, conductivity_s_m: float, *, clearance_um: float,
    source_model: str = "pointsource",
):
    """Apply a differential point- or line-source recorder to SWC membrane currents.

    The contacts and SWC geometry must share native micrometre coordinates.
    Returned values are microvolts; recording does not alter neuron dynamics.
    """
    from service.domain.model import Dynamics
    from service.infrastructure.lfpy.recording import (
        linesource_differential,
        pointsource_differential,
    )

    methods = {"pointsource": pointsource_differential, "linesource": linesource_differential}
    if source_model not in methods:
        raise ValueError("Unknown recording source model")

    geometry = np.asarray(result["starts_um"], dtype=float)
    ends = np.asarray(result["ends_um"], dtype=float)
    midpoints = np.asarray(result["midpoints_um"], dtype=float)
    radii = np.asarray(result["endpoint_radii_um"], dtype=float)
    diameters = np.asarray(result["diameters_um"], dtype=float)
    time = np.asarray(result["time_ms"], dtype=float)
    voltage = np.asarray(result["voltage_mv"], dtype=float)
    currents = np.asarray(result["membrane_current_na"], dtype=float)
    if (geometry.ndim != 2 or geometry.shape[1:] != (3,) or len(geometry) == 0
            or ends.shape != geometry.shape or midpoints.shape != geometry.shape
            or radii.shape != (len(geometry), 2) or diameters.shape != (len(geometry),)
            or time.ndim != 1 or len(time) < 2 or np.any(np.diff(time) <= 0)
            or voltage.shape != (len(geometry), len(time)) or currents.shape != voltage.shape
            or not all(np.isfinite(item).all() for item in
                       (geometry, ends, midpoints, radii, diameters, time, voltage, currents))
            or np.any(radii <= 0) or np.any(diameters <= 0)
            or not np.allclose(midpoints, (geometry + ends) / 2, rtol=1e-12, atol=1e-12)
            or not np.allclose(diameters, radii.sum(axis=1), rtol=1e-12, atol=1e-12)):
        raise ValueError("Invalid reference recording geometry or time series")
    dynamics = Dynamics(
        time,
        voltage,
        currents,
        geometry,
        ends,
        diameters,
        np.zeros(len(geometry), dtype=int),
        [0],
        [],
        0.0,
    )
    bipolar_potential_mv(
        result["midpoints_um"],
        electrode_um,
        reference_um,
        1,
        conductivity_s_m,
        clearance_um=clearance_um,
    )
    points = np.asarray([electrode_um, reference_um], dtype=float)
    validate_segment_clearance(result["starts_um"], result["ends_um"], points, clearance_um,
                               result["endpoint_radii_um"])
    return methods[source_model](dynamics, points, conductivity_s_m)


def record_swc_with_stimulus_artifact(
    result: dict, provenance: dict, electrode_um, reference_um, *, source_model: str = "pointsource"
):
    """Separate neural and direct stimulus terms in the ideal resistive medium.

    This is the instantaneous volume-conduction artifact only: electrode
    polarization, capacitive coupling and acquisition electronics are omitted.
    Contacts are native EM coordinates; no body-to-EM registration is implied.
    """
    config = provenance["configuration"]
    if not np.array_equal(_event_digest(config.get("synaptic_events")),
                          result.get("synaptic_events_sha256")):
        raise ValueError("Synaptic events do not match reference solution")
    shape = config.get("pulse_shape", "monophasic")
    if shape not in ("monophasic", "biphasic"):
        raise ValueError("Invalid stimulation pulse shape")
    conductivity = config["conductivity_s_m"]
    clearance = config["clearance_um"]
    parameters = np.asarray([
        *config["source_um"], *config["return_um"], config["current_na"], conductivity, clearance,
        config.get("pulse_start_ms", 2.0), config.get("pulse_end_ms", 3.0),
        config.get("rise_time_ms", 0.0),
        config.get("interphase_gap_ms", 0.0), 1 if shape == "biphasic" else 0,
        *([config['pulse_count'], config['pulse_interval_ms']]
          if config.get('pulse_count', 1) > 1 else []),
    ], dtype=float)
    if not np.array_equal(parameters, result["stimulation_parameters"]):
        raise ValueError("Stimulus configuration does not match reference solution")
    expected_field = bipolar_potential_mv(
        result["midpoints_um"], config["source_um"], config["return_um"],
        config["current_na"], conductivity, clearance_um=clearance,
    )
    if not np.allclose(expected_field, result["field_mv"], rtol=1e-12, atol=0):
        raise ValueError("Stimulus configuration does not match reference solution")
    fraction = np.asarray(result["stimulus_fraction"], dtype=float)
    lower_bound = -1 - 1e-12 if shape == "biphasic" else -1e-12
    if (fraction.shape != np.asarray(result["time_ms"]).shape or not np.isfinite(fraction).all()
            or np.any(fraction < lower_bound)
            or np.any(fraction > 1 + 1e-12)):
        raise ValueError("Invalid recorded stimulus waveform")
    time = np.asarray(result["time_ms"], dtype=float)
    start, end = config.get("pulse_start_ms", 2.0), config.get("pulse_end_ms", 3.0)
    rise, gap = config.get("rise_time_ms", 0.0), config.get("interphase_gap_ms", 0.0)
    from service.domain.pulse_train import pulse_train

    times, levels = pulse_train(start_ms=start, end_ms=end, rise_ms=rise,
                                interphase_gap_ms=gap, shape=shape,
                                duration_ms=config.get("duration_ms", 10.0),
                                count=config.get('pulse_count', 1),
                                interval_ms=config.get('pulse_interval_ms'))
    expected_fraction = np.interp(time, times, levels)
    # An instantaneous step has two valid one-sided values at the same time.
    # NEURON's sample convention there depends on floating-point integration.
    unambiguous = np.ones(time.shape, dtype=bool)
    boundary_allowed = np.zeros(time.shape, dtype=bool)
    for i in range(1, len(times)):
        if times[i] == times[i - 1] and levels[i] != levels[i - 1]:
            at_boundary = np.abs(time - times[i]) <= 1e-9
            unambiguous &= ~at_boundary
            boundary_allowed |= at_boundary & (
                np.isclose(fraction, levels[i - 1], rtol=0, atol=1e-9)
                | np.isclose(fraction, levels[i], rtol=0, atol=1e-9)
            )
    if not np.allclose(fraction[unambiguous], expected_fraction[unambiguous], rtol=1e-9, atol=1e-9):
        raise ValueError("Stimulus waveform does not match reference configuration")
    if not np.all(boundary_allowed[~unambiguous]):
        raise ValueError("Stimulus waveform does not match reference configuration")
    potential = bipolar_potential_mv(
        [electrode_um, reference_um], config["source_um"], config["return_um"],
        config["current_na"], conductivity, clearance_um=clearance,
    )
    artifact = (potential[0] - potential[1]) * 1000 * fraction
    neural = record_swc_reference(result, electrode_um, reference_um, conductivity,
                                  clearance_um=clearance, source_model=source_model)
    total = neural + artifact
    if not np.isfinite(total).all():
        raise ValueError("Non-finite recording")
    return {"neural_uv": neural, "stimulus_artifact_uv": artifact, "total_uv": total}


def simulate_registered_swc_reference(body_id: int, directories: list, *,
                                      expected_morphology_sha256: str | None = None, **parameters):
    """Run the isolated reference on an integrity-checked MaleCNS skeleton.

    The receipt identifies the morphology, not the biological validity of the
    membrane parameters or the electrode-to-body registration.
    """
    import inspect

    import neuron

    from service.infrastructure.connectome.morphology_repository import read_skeleton

    source = read_skeleton(body_id, directories)
    if expected_morphology_sha256 is not None and source["sha256"] != expected_morphology_sha256:
        raise ValueError("Source morphology digest mismatch")
    result = simulate_swc_reference(source["swc"], **parameters)
    bound = inspect.signature(simulate_swc_reference).bind(source["swc"], **parameters)
    bound.apply_defaults()
    config = dict(bound.arguments)
    config.pop("swc")
    if not config['nseg_by_edge']:
        config.pop('nseg_by_edge')
    else:
        config['nseg_by_edge'] = {
            str(node): count for node, count in config['nseg_by_edge'].items()}
    if config['record_membrane_current'] is True:
        config.pop('record_membrane_current')
    if config['field_coupling'] == 'extracellular':
        config.pop('field_coupling')
    if config['integration_order'] == 0:
        config.pop('integration_order')
    if config['solver_backend'] == 'neuron':
        config.pop('solver_backend')
    if config['experimental_hh_direct'] is False:
        config.pop('experimental_hh_direct')
    if config['pulse_count'] == 1:
        config.pop('pulse_count')
        config.pop('pulse_interval_ms')
    for name in ("source_um", "return_um"):
        config[name] = np.asarray(config[name], dtype=float).tolist()
    for name in ("current_na", "conductivity_s_m", "clearance_um", "dt_ms", "duration_ms",
                 "pulse_start_ms", "pulse_end_ms", "rise_time_ms", "interphase_gap_ms",
                 "axial_resistivity_ohm_cm",
                 "membrane_capacitance_uf_cm2", "temperature_c", "initial_voltage_mv"):
        config[name] = float(config[name])
    components = neurite_landmark(source["swc"])["components"]
    numerical_order = config.get('integration_order', 0)
    return result, {
        "body_id": source["body_id"],
        "morphology_sha256": source["sha256"],
        "morphology_source": source["source"],
        "source_units": source["source_units"],
        "vertices": source["vertices"],
        "membrane_model": "NEURON built-in hh; engineering reference, not Drosophila calibrated",
        "stimulation_model": "bipolar point sources; infinite homogeneous isotropic conductor",
        "coordinate_frame": "MaleCNS native EM, micrometres",
        "configuration": config,
        "fixed_parameters": {"channel_parameters": "NEURON hh built-in defaults",
                             "hh_kinetics": ("direct" if parameters.get('experimental_hh_direct')
                                             else "tabulated"),
                             "integration": f"fixed step, NEURON secondorder={numerical_order}"},
        "components": components,
        "fragment_interpretation": (
            "disconnected fragments remain electrically independent; connectivity is unknown"
            if components > 1
            else "one connected SWC component"
        ),
        "neuron_version": neuron.__version__,
        "numpy_version": np.__version__,
    }
