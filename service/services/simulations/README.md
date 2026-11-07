# Simulation service

`api.py` owns authenticated endpoints and the event stream; `tasks.py` owns the
queue lifecycle and result publication. `models.py` holds persistent state and
`runtime.py` provides infrastructure adapters.

- `inputs/` validates and transfers owned inputs for each execution type.
  `inputs/spatial.py` contains native-field, contact and spatial-search request
  contracts and response validation; the API retains the HTTP endpoints.
- `manifests/` validates result manifests and their previews before publication.
- `failure_codes.py` maps execution failures to the public contract.

Keep ownership checks at the API boundary and do not treat Redis progress as
the durable state of a run.
