# AISCS fork

Base upstream package: MemoryOS 2.0.23 (Apache-2.0). The local package version
`2.0.23+aiscs.1` identifies this fork; it is not an upstream 2.0.24 release.

- Ignore local `.work/` execution artifacts.
- The standalone Docker example uses the existing `NEO4J_USER` and
  `NEO4J_PASSWORD` variables instead of a hardcoded shared password. Supply the
  private environment explicitly when running Compose. The original environment
  template and the SDK logic are retained.

These configuration changes do not constitute a validation of the optional
MemOS service in the AISCS simulation profile.
