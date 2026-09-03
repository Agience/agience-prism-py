# Changelog

All notable changes to `agience-prism` are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.1]

First public release.

### Added

- The contract, in a base install with no dependencies: canonical JSON (RFC 8785 JCS), the crystal
  model, the capability vocabulary, the config shape, the typed error set, and the structural
  address. `resolution` and `adaptive_cut` compute on bare stdlib alongside it.
- `prism.Host` — compute that serves capabilities over HTTP, under the `host` extra.
- `prism.create_server` — an MCP server that acts within the calling user's authorization, under the
  `server` extra.
- `prism.trust` — keys, service and delegation JWTs, scopes, under the `trust` extra.
- The wire: reach, plane, streams, carriers, frames, propagation, mcp_bridge, schema, demurrage,
  minting, settlement, pump, minhash, error_threshold, extraction, conservation. Nine of the sixteen
  import on the bare base install; the rest are under the `wire` extra.
- `prism.runner` — the bundle loader, with sha verification before any exec.
- The `prism` command line: `init`, `list`, `install`, `publish`, under the `cli` extra.
- The shared conformance vectors ship inside the wheel (`prism.vectors`), so a conformance gate runs
  from `pip install agience-prism` alone.
- `py.typed` (PEP 561): the annotations throughout the package are visible to consumers' type
  checkers.

[Unreleased]: https://github.com/Agience/agience-prism-py/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/Agience/agience-prism-py/releases/tag/v0.1.1
