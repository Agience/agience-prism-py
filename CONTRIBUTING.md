# Contributing to Agience Prism (Python)

One of three SDK repos — `py`, `js`, `c` — implementing one prism contract. **`py` owns the
canonical capability vocabulary.** The distribution published from this repo is `agience-prism`.

## The rule that spans all three

The capability vocabulary must agree across the SDKs. Each is written independently, so one can add
or misspell a name without the others noticing — and a host built against one can then sign a
manifest another rejects. Canonical home: `prism/capabilities.py` (`CAPABILITY_KINDS`); `sensor.*`
and `actuator.*` are open families accepted by prefix.

**Add to the canonical list here, then to all three SDKs, in that order, one PR.** Maintainers run
the cross-SDK drift check before merge; it parses each SDK's source rather than importing it, so it
needs neither a C++ toolchain nor node nor prism installed.

## Tests

```bash
pip install -e ".[dev]"
python -m pytest -q
python -m ruff check .
```

`tests/` imports nothing outside this package and reads no path outside this checkout. Prism is a
DAG root: it depends on nothing in the workspace, and a gate that needs a second repo belongs in
that repo or in the workspace's own gate directory, not here.

## The base install is the contract, and it has no dependencies

Enforced by `tests/test_contract_install_is_pure.py`. Runtime surfaces (`trust`, `host`, `server`,
`cli`, `vector`, `wire`) are **extras**. This is not tidiness: when the base imported host and
server eagerly, reading one constant pulled in a web framework, and two components vendored
`canonical.py` rather than depend on this package.

A dependency added here lands on every install path that reaches prism. Keep the three SDKs' public
surfaces recognisably the same shape — a convenience that exists in one language only becomes a
contract difference the moment someone uses it.

## `prism/canonical.py` is the JCS canonicaliser of record

Every content address and signature is taken over its output, and it is the only copy of it.
**Changing it re-addresses stored content** — a migration decision, not an edit.

## Versioning

`prism.__version__` is the version of record; `pyproject.toml` reads it from there, and `prism.host`
and `prism.server` re-export it. Release by pushing a `v<version>` tag: the release workflow builds,
checks the tag against the built artifact, creates the GitHub Release, and publishes to PyPI through
Trusted Publishing. Record the change in `CHANGELOG.md` in the same PR that makes it.

## Contributing

Fork, branch from `main`, sign off every commit (`git commit -s`) to certify the
[DCO](https://developercertificate.org/), open a PR. Commit format: `fix:` / `feat(scope):` /
`docs:` / `test:` / `chore:`. By contributing you agree your contribution is Apache-2.0 (per section
5), including its section 3 patent grant.

**Security vulnerabilities: do not open a public issue** — see [`SECURITY.md`](SECURITY.md), or
email **connect@agience.ai**.

## License

Apache-2.0 — see [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).
