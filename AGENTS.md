# `agience-prism-py` — the shared foundation (Python)

One of **three** SDK repos — `py`, `js`, `c` — sitting in the plain directory `agience-prism/`, which
is not itself a repo. They implement the same prism contract in three languages. This repo publishes
to PyPI as **`agience-prism`**; the repo keeps the `-py` name.

## Prism is a DAG root, and self-contained

It depends on nothing else in the workspace, imports nothing from the components that depend on it,
and resolves no path outside its own installation. Where a deployment supplies data — operator
bundles for `prism.runner` — it names the directory with `$AGIENCE_BUNDLE_ROOT` or binds a payload
with `register_group()`.

A walk up parent directories to a sibling checkout is the thing to keep out. It makes the package
behave differently inside the workspace than it does installed, which means a test can pass here and
fail for every consumer — and for a content-addressed payload it is worse than that: a second copy
can drift from the bytes the mesh carries while the sha gate keeps passing on the wrong file.

A gate that needs a second repo belongs in that repo, or in the workspace's own gate directory. It
does not belong in `tests/`.

## The rule that spans all three SDKs

**The capability vocabulary must agree across the SDKs.** Each one's vocabulary is compiled or
hand-typed independently, so one SDK can add, drop or misspell a capability name without the others
noticing — and a host built against one SDK's names can sign a manifest another SDK's server
rejects.

`agience-cloud/deploy/capability_drift.py` checks this by **parsing** each SDK rather than importing
it, so the check does not need a C++ toolchain, node, or prism installed. The canonical home is
`prism/capabilities.py` (`CAPABILITY_KINDS`); `sensor.*` and `actuator.*` are open families accepted
by prefix.

**Adding a capability name to one SDK only is the failure this exists to catch.** Add it to the
canonical list, then to all three, then run the check.

## This repo is public

`github.com/Agience/agience-prism-py` is public and publishes to PyPI. Two things follow:

- Internal hostnames, endpoints and private-repo paths do not belong in tracked files, including
  runtime error messages. `.vscode/` is untracked here for that reason, while it is tracked in the
  private repos.
- A dependency added here lands on every install path in the workspace, and on every consumer
  outside it. The base install is the contract and carries no dependencies; runtime surfaces are
  extras.

## Working here

- Keep the three SDKs' public surfaces recognisably the same shape. A convenience that exists in one
  language only becomes a contract difference the moment someone uses it.
- `prism/canonical.py` is the JCS canonicaliser of record for the whole workspace. Changing it
  re-addresses stored content — a migration decision, not an edit.
- `prism.__version__` is the version of record; `pyproject.toml` reads it from there.
