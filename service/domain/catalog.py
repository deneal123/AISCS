from service.contracts import Placement, RegistrationContext, SimulationConfig
from service.domain.geometry import local_geometry
from service.domain.scene_context import scene_context
from service.domain.visualization import VISUALIZATION

LIMITATIONS = [
    "Author-defined compartmental chain in an adult VNC anatomical context; "
    "not a reconstructed connectome.",
    "Generic Hodgkin-Huxley membrane parameters are engineering defaults, "
    "not fitted Drosophila parameters.",
    "Homogeneous isotropic infinite conductor; no cuticle/tissue boundary model.",
    "Extracellular recording of model activity does not measure subjective pain or human ECAP.",
    "Body reaction is a phenomenological visualization, not validated biomechanics.",
]


def catalog(*, connectome_available: bool = False) -> dict:
    context = scene_context()
    defaults = SimulationConfig(
        placement=Placement(
            mesh_asset_id=context["mesh_asset_id"], registration=RegistrationContext(**context)
        )
    )
    local = {
        "id": "local-compartment-chain-v1",
        "name": "Локальная компартментная цепь",
        "organism_context": "adult Drosophila VNC",
        "geometry_origin": "author-defined schematic",
        "geometry": local_geometry(),
        "scene_context": scene_context(),
        "visualization": VISUALIZATION,
        "solver": "NEURON",
        "recording_operator": "LFPy/lfpykit pointsource, E1 minus REF",
        "regions": [{"id": "thoracic-local-v1", "name": "Локальная грудная область"}],
        "units": {"time": "ms", "position": "um", "voltage": "mV", "current": "nA", "signal": "uV"},
        "defaults": defaults.model_dump(mode="json"),
        "limitations": LIMITATIONS,
    }
    available = connectome_available
    full_defaults = defaults.model_copy(
        update={"model_id": "male-cns-hybrid-v1", "stimulus_region": "thorax"}
    )
    full = {
        **local,
        "id": "male-cns-hybrid-v1",
        "name": "Полный граф ЦНС · MaleCNS",
        "available": available,
        "solver": "Full registered LIF CNS + local NEURON projection",
        "geometry_origin": "MaleCNS v1.0 annotated non-glial graph; view-only embedding",
        "defaults": full_defaults.model_dump(mode="json"),
        "neurons": 166700,
        "edges": 25582938,
        "input_regions": [
            {"id": key, "name": name, "available": key != "abdomen"}
            for key, name in [
                ("head", "Голова"),
                ("thorax", "Грудь · все ноги"),
                ("abdomen", "Брюшко"),
                ("front_left", "Передняя левая нога"),
                ("front_right", "Передняя правая нога"),
                ("middle_left", "Средняя левая нога"),
                ("middle_right", "Средняя правая нога"),
                ("hind_left", "Задняя левая нога"),
                ("hind_right", "Задняя правая нога"),
            ]
        ],
        "limitations": [
            "All registered CNS neurons are calculated; display edges use LOD.",
            "Tactile input is a model drive, not calibrated noxious stimulation.",
            "Peripheral paths are schematic; missing soma positions are not reconstructed.",
            "Local E1−REF is from six HH proxy cells; not a full-CNS voltage solution.",
            "Spikes and body animation do not establish subjective pain.",
        ],
    }
    return {
        "contract_version": "1.0",
        "default_model_id": full["id"] if available else local["id"],
        "models": [local, full],
    }
