# Simulator interface

`SimulatorPage.jsx` coordinates the experience and `SimulatorScene.jsx` owns
the scene. Shared API and theme definitions remain at this level.

- `connectome/` loads and displays CNS geometry and neuron connections.
- `field/` contains stimulation geometry and contact tools.
- `recording/` contains the unified calculation workflow, traces and replay.
- `scene/` contains body geometry, camera, motion and placement helpers.
- `components/` contains the experiment sidebar, scene visibility controls and
  calculation status. They receive state and callbacks from `SimulatorPage`.

The calculation status uses measured events when available. A running stage
without measured work is indeterminate; its progress must not be fabricated.
