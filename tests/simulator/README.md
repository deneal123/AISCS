# Live simulator scene checks

These tests use the running isolated AISCS development stack. They do not start
or stop Docker services. Use a disposable authenticated account and its saved
completed strong-stimulus run. Cookie state belongs in ignored `.work`, never Git.

From `frontend` in PowerShell:

```powershell
$env:SIMULATION_E2E_STATE = 'R:/Aspa/.work/generator-implementation/browser-state.json'
$env:SIMULATION_E2E_RUN = '<completed run UUID>'
$env:SIMULATION_E2E_FIXTURES = 'R:/Aspa/.work/generator-implementation/comparison-fixtures.json'
npx playwright test --config tests/simulator/playwright.config.js
```

The 1366×768 and 1920×1080 checks exercise the actual asset and rendering,
reduced-motion behavior, explicit playback, recorded-event-driven leg response,
transparency, source-surface selection, invalid electrode clearance, Escape and
reload. They also check the view-only local window, idle render suppression and
the requirement to apply/cancel placement before starting a run. Screenshots
and traces go to the superproject's ignored `.work`.
One additional scenario executes a real queued calculation and checks the
published surface anchor, input journal, shared scene/plot clock and input cue.
It also requires an actual WebSocket snapshot for that run; HTTP fallback alone
cannot satisfy this assertion.

`comparison.live.spec.js` requires the optional fixtures file. It contains a
`runs` dictionary with owned completed records `none`, `weak`, `strong`,
`adaptation`, `electrode` and `incompatible`. Each record supplies `id`,
`peak_signal_uv` and `cache.data_sha256`; `same_currents_electrode_pair` confirms
the shared source-current export for the strong/electrode pair. Prepare these
through the normal authenticated API; never copy another user's credentials or
change ownership to satisfy the checks. The two compatible records share the
full registered frame, actual time grid, units and engine/operator provenance.
The incompatible record uses a different duration.

These scenarios check shared camera by pointer and keyboard, one clock and
physical amplitude range, all three conditions, adaptation, changed electrode,
local focus, pair restoration after reload, incompatible data, missing A and
new-experiment reset. Viewing saved records must send zero calculation requests.
They inspect prediction errors without retuning the frozen classifier.

`workflow.live.spec.js` checks fullscreen and Escape, cancellation of uncommitted
placement on navigation, real `WEBGL_lose_context` loss and explicit renderer
recovery, read-only artifact retry, and downloaded manifest/CSV hashes. Its 503
injection persists through the shared client's bounded GET retries until the
manual retry is visible. The history test sends real owner-filtered list requests
with smaller server pages; it does not fabricate records or submit calculations.
Source selection checks hover, a view-only region and the registered surface;
attached picking timings describe a few actual raycasts, not a performance bound.
Changing draft stimulus parameters must retain a clear saved-record caption.
The test skips without explicit state/run settings. It does not validate
biological behavior or the classifier's generalization.

`connectome.live.spec.js` uses additional owner-scoped completed records:

```powershell
$env:SIMULATION_E2E_FULL_CNS = '<MaleCNS strong run UUID>'
$env:SIMULATION_E2E_FULL_CNS_QUIET = '<MaleCNS quiet run UUID>'
$env:SIMULATION_E2E_FULL_CNS_MOVED = '<same dynamics, moved E1 run UUID>'
npx playwright test --config tests/simulator/playwright.config.js connectome.live.spec.js
```

The whole-CNS checks cover all 166,700 rendered nodes, actual saved spike events,
quiet control, rewind, idle rendering, source-mesh input selection, separation
from electrode placement, two synchronized scenes and buffer-read recovery.
They never submit another calculation. Missing fixture variables skip these
scenarios explicitly. The separate frozen full-CNS classifier is checked by
`recognition.live.spec.js` with `SIMULATION_E2E_RECOGNITION` set to a JSON object
containing owned `head` and `outside` completed run IDs. The tests preserve the
known head-example error, show regional versus overall test sizes, restore after
reload, and reject fabricated predictions outside checked conditions. These
runtime examples are separate from the held-out accuracy estimate.
