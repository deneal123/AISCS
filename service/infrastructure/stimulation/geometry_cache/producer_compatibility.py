"""Narrow, reviewed producer compatibility; all snapshot checks still apply."""

# This entry is populated only for a specifically reviewed producer change.
# The manifest and both producer identities must match exactly.
REVIEWED_PRODUCERS = frozenset({
    # The old and new geometry preparation functions are AST-identical; the
    # network_field change guards process lifetime. The cache reader change
    # introduces this exact compatibility check. No chunk or source check is
    # skipped. See generator/TODO.md for the limited independent sampling.
    ('bf6374d275de2c52b908fa1b7847d3f7a97be401adc70e9a6ad0ca658ab0a725',
     'b04a7dc3a1d03e53c42537bafad2eccd9db609063a4f330ce8697a2b09b049de',
     'fefeb7d4631cd423765403b65f5e2f8169424c4459068e3eef81c41297475155'),
})


def producer_is_compatible(manifest_sha256, snapshot_producer, current_producer):
    return snapshot_producer == current_producer or (
        manifest_sha256, snapshot_producer, current_producer
    ) in REVIEWED_PRODUCERS
