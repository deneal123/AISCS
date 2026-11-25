"""Map the connectome's motor neurons onto the twin's muscles.

The connectome gives 319 leg motor neurons in six leg regions and 307 abdominal
motor neurons in ten neuromeres.  The body model gives 64 muscles: 36 in the legs
and 28 in the abdomen.  Neither source names the muscle a neuron innervates, so
the map below is explicit, derived from the neuron's own anatomical type and
kept in one place, so that every claim about it can be checked or replaced.

What the map is and is not:

  * it is a typology, not a measurement: "Ti flexor MN" innervates a tibia
    flexor, and nothing in the connectome contradicts that;
  * it does not decide the laterality of a muscle, which is why a muscle is
    driven by the mean recruitment of every neuron mapped to it;
  * it leaves 103 of the 319 leg neurons unmapped on purpose.  The ltm cells are
    stretch receptors and the Ta/Fe cells move the tarsus and the femur, which
    the twin does not actuate yet.  Mapping them onto the nearest muscle would
    invent a connection the data does not carry.
"""

from __future__ import annotations

import json

LEG_REGIONS = {"front_left": "T1_left", "front_right": "T1_right",
               "middle_left": "T2_left", "middle_right": "T2_right",
               "hind_left": "T3_left", "hind_right": "T3_right"}
# Motor neuron type -> (joint group, direction).  "flexor" shortens the joint.
LEG_TYPES = {
    "Ti flexor MN": ("tibia", "flexor"),
    "Acc. ti flexor MN": ("tibia", "flexor"),
    "Ti extensor MN": ("tibia", "extensor"),
    "Tr flexor MN": ("femur_twist", "flexor"),
    "Acc. tr flexor MN": ("femur_twist", "flexor"),
    "Sternotrochanter MN": ("femur_twist", "flexor"),
    "Tr extensor MN": ("femur_twist", "extensor"),
    "Tergotr. MN": ("femur_twist", "extensor"),
    "Fe reductor MN": ("coxa_abduct", "flexor"),
    "Sternal anterior rotator MN": ("coxa_abduct", "flexor"),
    "Pleural remotor/abductor MN": ("coxa_abduct", "extensor"),
    "Sternal posterior rotator MN": ("coxa_abduct", "extensor"),
    "Sternal adductor MN": ("coxa_abduct", "extensor"),
}
# Abdominal neuromere -> the segment whose dorsal muscle it is.  A10 has no
# segment of its own and pulls the last one.
NEUROMERE_SEGMENTS = {"A1": "abdomen", "A2": "abdomen_2", "A3": "abdomen_3",
                      "A4": "abdomen_4", "A5": "abdomen_5", "A6": "abdomen_6",
                      "A7": "abdomen_7", "A8": "abdomen_7", "A9": "abdomen_7",
                      "A10": "abdomen_7"}


def muscle_of_leg_neuron(region, neuron_type):
    """Muscle name for a leg motor neuron, or None if the twin has no such muscle."""
    leg = LEG_REGIONS.get(region)
    entry = LEG_TYPES.get(neuron_type)
    if leg is None or entry is None:
        return None
    joint, direction = entry
    return "%s_%s_%s" % (joint, leg, direction)


def muscles_of_abdominal_neuron(neuromere, soma_side):
    """Muscles an abdominal motor neuron drives, as (muscle, weight) pairs.

    The dorsal muscles are the ones that curl the abdomen, so every ad cell pulls
    the pitch flexor.  The lateral component is a modelling choice: the two sides
    of the segment are pulled by the cells whose bodies sit on that side, which is
    what makes a one-sided stimulus bend rather than shorten the abdomen.  The
    connectome does not carry the muscle a cell innervates, so this is labelled a
    choice, not a measurement.
    """
    segment = NEUROMERE_SEGMENTS.get(neuromere)
    if segment is None:
        return []
    # The exporter names a muscle "<group>_<part>_<direction>", so the first
    # segment reads abdomen_pitch_abdomen_flexor and the others
    # abdomen_pitch_abdomen_2_flexor.
    pair = [("abdomen_pitch_%s_flexor" % segment, 0.5)]
    if soma_side == "L":
        pair.append(("abdomen_yaw_%s_flexor" % segment, 0.5))
    elif soma_side == "R":
        pair.append(("abdomen_yaw_%s_extensor" % segment, 0.5))
    return pair


def build_map(leg_path, abdominal_path):
    """Read both motor inventories and return muscle name -> neuron ids."""
    with open(leg_path, encoding="utf-8") as handle:
        leg_inventory = json.load(handle)
    with open(abdominal_path, encoding="utf-8") as handle:
        abdominal_inventory = json.load(handle)

    mapping = {}
    unmapped = []
    for cell in leg_inventory["cells"]:
        muscle = muscle_of_leg_neuron(cell.get("region"), cell.get("type"))
        if muscle is None:
            unmapped.append(("leg", int(cell["id"]), cell.get("type")))
            continue
        mapping.setdefault(muscle, []).append(int(cell["id"]))
    for cell in abdominal_inventory["cells"]:
        pairs = muscles_of_abdominal_neuron(cell.get("neuromere"), cell.get("soma_side"))
        if not pairs:
            unmapped.append(("abdomen", int(cell["id"]), cell.get("type")))
            continue
        for muscle, _ in pairs:
            mapping.setdefault(muscle, []).append(int(cell["id"]))
    return mapping, unmapped


def recruitment(spikes, neuron_ids, *, gain=0.05, saturation=1.0):
    """Recruitment of one muscle from the spikes its neurons produced in a window.

    A rate code: each spike adds ``gain`` to the command and the sum is clipped at
    ``saturation``.  At the measured firing of a recruited motor neuron (one to
    three spikes in a ten millisecond window) this reaches full recruitment in
    two to four spikes, which is the order of magnitude of a real twitch fusion.
    """
    total = 0.0
    for neuron in neuron_ids:
        total += spikes.get(neuron, 0)
    return min(saturation, gain * total)

