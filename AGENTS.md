# `agience-prism-py` - the shared foundation (Python)

One of **three** SDK repos - `py`, `js`, `c` - sitting in the plain directory `agience-prism/`,
which is not itself a repo. They implement the same PRISM CONTRACT in three languages.

## The rule that spans all three

**The capability vocabulary must agree across the SDKs.** Each one's vocabulary is compiled or
hand-typed independently, so one SDK can add, drop or misspell a capability name without the others
noticing - and a host built against one SDK's names can sign a manifest another SDK's server
rejects.

`agience-cloud/deploy/capability_drift.py` checks this by **parsing** each SDK rather than importing
it, so the check does not need a C++ toolchain, node, or prism installed. The canonical home is
`prism/capabilities.py` (`CAPABILITY_KINDS`); `sensor.*` and `actuator.*` are open families accepted
by prefix.

**Adding a capability name to one SDK only is the failure this exists to catch.** Add it to the
canonical list, then to all three, then run the check.

## Working here

- This is a **foundation** package: things depend on it and it depends on as little as possible.
  A dependency added here lands on every install path in the workspace.
- Keep the three SDKs' public surfaces recognisably the same shape. A convenience that exists in one
  language only becomes a contract difference the moment someone uses it.
