# Simulation contracts

`field/` contains requests and receipts for field summaries and graph execution;
`population/` contains requests for fragment selection, recordings and feedback;
`replay.py` defines the independent registered-cell replay contract. Each
contract validates its own configuration and preserves the existing JSON
field names and digest rules.

Contracts describe the requested calculation and its provenance. They do not
imply complete biophysical recording, physiological calibration, or a
validated nociceptive response.
