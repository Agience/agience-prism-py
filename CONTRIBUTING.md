# Contributing to Agience Prism (Python)

One of three SDK repos - `py`, `js`, `c` - implementing one PRISM CONTRACT. **`py` owns the
canonical capability vocabulary.**

## The rule that spans all three

The capability vocabulary must agree across the SDKs. Each is written independently, so one can add
or misspell a name without the others noticing - and a host built against one can then sign a
manifest another rejects. Canonical home: `prism/capabilities.py` (`CAPABILITY_KINDS`); `sensor.*`
and `actuator.*` are open families accepted by prefix.

```bash
python ../../agience-cloud/deploy/capability_drift.py
```

**Add to the canonical list, then to all three SDKs, then run the check - in that order, one PR.**

## Tests

```bash
python -m pytest -q tests
```

`tests/` imports nothing else from the workspace; prism is a DAG root.

## The base install is the contract, and it has no dependencies

Enforced by `tests/test_contract_install_is_pure.py`. Runtime surfaces (`trust`, `host`, `server`,
`cli`, `vector`, `wire`) are **extras**. This is not tidiness: when the base imported host/server
eagerly, reading one constant pulled a web framework, and two repos vendored `canonical.py` rather
than depend on this package.

## `prism/canonical.py` is the JCS canonicaliser of record

Every content address and signature is taken over its output, and it is now the only copy of it in
the workspace. **Changing it re-addresses stored content** - a migration decision, not an edit.

## Contributing

Fork, branch from `main`, sign off every commit (`git commit -s`) to certify the
[DCO](https://developercertificate.org/), open a PR. Commit format: `fix:` / `feat(scope):` /
`docs:` / `test:` / `chore:`. By contributing you agree your contribution is Apache-2.0 (per section
5), including its section 3 patent grant.

**Security vulnerabilities: do not open a public issue** - email **connect@agience.ai**.

## License

Apache-2.0 - see [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).
