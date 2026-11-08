# Changelog

All notable changes to `agience-prism` are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.9] - 2026-11-08

### Changed (review 31)
- The version is 0.1.9. 0.1.8 is already tagged, and the changes below shipped after it, so Origin, Mantle, Crystal, Chorus and Ember floor `agience-prism` at 0.1.9.

### Changed (review 29)
- `ledger.ENTRY_KINDS` includes `root.confirm_empty`, the operator's confirmation that nothing is left under a root's master key.

### Changed (review 28)
- `service_identity.SERVER_DELEGATION_SIGNERS`: the personas and Crystal, the services that hold a server delegation of their own.

### Changed (review 27)
- `shamir.shares_through` gives the other shares of the k=2 split a known share belongs to, so an interrupted split is finished with that share kept.
- `ServerAuth._mint_delegation_for_user` is removed: a persona exchanges only the delegation Origin narrowed to it.

### Changed (review 25)
- `verify_jwt` also maps an `ArithmeticError` to `JWTError`.

### Changed (review 24)
- `verify_jwt` raises `JWTError` for a claim of the wrong type, such as a null or odd `exp`.

### Changed (review 23)
- A persona exchanges an inbound describe delegation for its own copy addressed to Mantle (`ServerAuth(describe_exchange=)`), and keeps only that.
- The host `TokenVerifier` refuses a delegation naming no actor and a principal type that is neither a caller nor a service.

### Changed (review 22)
- `ServerAuth.verify_origin_delegation` refuses a delegation this persona asked for itself (`act.iss` its own name).
- `use_verdict.verify` requires the sealed copy, the endpoint list and the nonce, and compares them with the verdict's `sealed_sha256`, `endpoints_sha256` and `nonce` (`sealed_digest`, `endpoints_digest`).

### Changed (review 21)
- `prism.trust.use_verdict`: the names of Origin's verdict for a secret's use, and the persona's check of it and of the delegation it acts on.
- `TokenVerifier` ties each `kid` to its anchor and requires `iss` to be that anchor's name; only the `origin` anchor may sign as the manifest's issuer.

### Changed (review 19)
- A persona takes a delegation from Origin only: the Mantle-signed path is removed from the middleware and from `ServerAuth`, and `verify_delegation_jwt` refuses `expected_issuer="mantle"`.
- `prism.trust.ledger.canonical_reach` and `canonical_expiry`: the one digest form, with expiry, invite target and claim limit.

### Added (review 17)
- `prism.trust.ledger`: the authority ledger's names, shared by Origin and Mantle (`CREDENTIAL_KINDS`, `MANTLE_APPLIES`, `ENTRY_KINDS`, `GENESIS`, `LEDGER_VERSION`, `COLLECTION_KEY_PREFIX`, `target_digest`).

### Changed (review 14)
- `NotBefore` accepts a bounds document only when its `iat` is no older than the last one accepted (kept in the state file), is inside the `STALE_SECONDS` window, and is not more than `SKEW_SECONDS` ahead of the clock. A replayed document is no good poll.

### Changed (review 12)
- `verify_origin_jwt`: an Origin token's `iss` must be the authority manifest's issuer. `verify_access_token`, `ServerAuth.verify_origin_delegation` and `verify_narrowed_delegation` use it, so another issuer's token (a staging Origin's) is refused.
- The sign-in bounds poller reads Origin's rows by sequence (`after=<seq>`), keeps the bounds in its own state file (`NOT_BEFORE_STATE`, else `$KEYS_DIR/not_before.json`), refuses every token until its first good poll after a start and once its last good poll is older than `AGIENCE_NOT_BEFORE_STALE_SECONDS` (120), and refuses a token with no `iat`. `AGIENCE_NOT_BEFORE_NO_POLL` is honoured only under pytest.

### Added (review 11)
- `prism.trust.not_before`: Origin's published sign-in bounds (`GET /auth/not-before`), polled every 15 seconds and checked against Origin's signature; `refused(claims)` answers whether a token was issued before its person's bound or everyone's.

### Changed (review 11)
- A persona never receives or forwards a person's own access token: `ServerAuth` takes a caller only as Origin's delegation narrowed to that persona (`aud` = `act.sub` = its name, scope `persona:<name>`), which it exchanges for its own server delegation; a person's full token is refused, never exchanged, and never kept to pass on. Tokens issued before their person's sign-in bound are refused.

## [0.1.8] - 2026-10-31

### Added
- `prism.trust.shamir`: Shamir k-of-n secret sharing over GF(256), standard library only. It is the one implementation in the platform: Origin's key oracle re-exports it as `origin.services.shamir`, and Mantle's threshold master-key custody splits and combines with it.

### Fixed
- `shamir.combine` refuses shares of different lengths, a share whose x-coordinate is outside 1..255, and duplicate x-coordinates. The copy Origin held returned wrong bytes with no error for a shorter first share and for x = 0.

## [0.1.7] - 2026-10-29

### Added
- `.github/workflows/publish.yml` now also runs on pushes to `release/**` branches. It builds and checks the package as it does for version tags, then keeps the files as a `dist` artifact so the platform release deploys exactly that build.

## [0.1.6] - 2026-10-22

### Fixed
- A test no longer assigns a lambda to a name, which GitHub's lint step refused (ruff E731) on `main` and the `v0.1.5` tag.

## [0.1.5] - 2026-10-18

### Added
- A persona admits a platform service calling it: a service JWT addressed to the persona and signed by an enrolled key (`ServerAuth.verify_platform_service`) reaches it as a service (`request_service_caller`), with no person to act for, so only operations a persona opens to platform services answer it. Every such caller was refused at the door.
- `prism.trust.sealing`: a secret sealed to the one key that will use it (RSA-OAEP-256 wrapping an AES-256-GCM key), bound to its context (the recipient's key id, the secret, the card it was released for). It opens only with that key, for that use.
- A chorus persona may hold its own key pair (`<name>.private.pem`, `service_identity.PERSONA_NAMES`, `load_persona_identity`) and makes its delegation exchange signed with it (`ServerAuth.sign_exchange_jwt`), so Origin can prove which persona the delegation is for. Every persona signed as the shared `chorus` identity and named itself in a claim.
- A persona keeps the caller's own credential (`ServerAuth.request_caller_token`) beside the delegation it exchanged it for — a person's access token or a grant key, never a delegation addressed to it — so a call it makes to another persona carries what that persona accepts. A persona forwarded its own delegation, which every other persona refuses.
- A persona's inbound auth carries a grant key (`agk_…`, bare or artifact-scoped) to the store as-is: its grants are the whole of what it may do, and Mantle decides every call. A persona called with one tried to exchange it at Origin, was refused, and answered 401, so nothing could run on a key a person issued (an agent, a timer). `prism.trust.server_auth.is_grant_key` names the shape.

## [0.1.4] - 2026-10-09

### Breaking

- `prism.host` (`Host`, `TokenVerifier`) now refuses every operator call when no credential is configured. Serving without authentication requires the explicit keyword `allow_open=True`; no environment variable enables it.
- `prism.host` refuses a JWT unless `expected_audiences` (or `HOST_EXPECTED_AUDIENCES`) is set. Accepting a JWT for any audience requires `any_audience=True`, which also has no environment variable.
- `Host.serve` binds `127.0.0.1` by default instead of `0.0.0.0`; pass `host="0.0.0.0"` to listen on all interfaces.
- `prism.trust.ServerAuth.verify_user_jwt` now returns `None` for refresh, email-verification, password-reset, `server` and `service` tokens, for delegation tokens, and for a first-party user token not addressed to the authority issuer.
- `prism.source.Observation.to_doc()` now renders `state="live"` instead of `state="committed"`.
- The `screen_read_vectors.json` conformance vector `collapsed_axis` now pins `scale_hazard` as `true` for the `beam` engine, and the known-divergence list drops from six entries to five.

### Added

- `prism.access_token` module, with no dependencies, holds the claim rule for taking a verified Origin token as a caller's identity. It exposes `purpose_refusal`, `caller_refusal` and `issuer_origin`, each returning a reason string or `None`.
- `prism.trust.verify_access_token` verifies an Origin-signed token and applies the caller rule, raising `JWTError` when the claims are not a caller's access token.
- `Host` and `TokenVerifier` accept `allow_open` and `any_audience` keywords. `TokenVerifier.audience_checked` reports whether a JWT can be accepted, and `describe()` states when no credential is configured or JWTs are refused.
- README badges for PyPI, supported Python versions, license, CI and sponsorship.

### Changed

- `prism.host` refuses any JWT carrying a `token_type` claim, so Origin's refresh, email-verification and password-reset tokens are not accepted as credentials.
- `Host` logs an error at startup when no credential is configured, and a warning when a JWT source has no expected audience.
- The package version is `0.1.4`.
- Package discovery is limited to `prism*`, so only the `prism` package is installed.
- Ruff lint rules are pinned to `E4`, `E7`, `E9` and `F`.
- CI runs the test suite and ruff on Python 3.11, 3.12 and 3.13.
- The README and `CONTRIBUTING.md` are shortened. `README.md` documents the new `Host` auth behaviour and loopback bind.

### Removed

- `SECURITY.md`, the root `FUNDING.yml` (replaced by `.github/FUNDING.yml`) and the tracked `AGENTS.md` are no longer in the repository.

## [0.1.4]

### Added

- `prism.access_token` (base install): the claim rule for Origin-signed tokens. `purpose_refusal`
  refuses any token carrying a `token_type` claim (refresh, email verification, password reset);
  `caller_refusal` also requires a caller principal (user, `mcp_client`, delegation), a user token
  addressed to the authority issuer, and a delegation addressed to the service's own client ids.
- `prism.trust.verify_access_token`: the signature against the `origin` anchor, then that rule.

### Security

- `ServerAuth.verify_user_jwt` accepts only access tokens. It accepted any Origin-signed token with
  an audience, including refresh, email-verification and password-reset tokens.
- `prism.Host` / `TokenVerifier` fail closed. With no credential configured every operator call is
  refused unless `allow_open=True`; with no `expected_audiences` every JWT is refused unless
  `any_audience=True`; a JWT carrying `token_type` is refused. `Host.serve` binds `127.0.0.1` by
  default.

## [0.1.3]

### Changed

- `source.Observation.to_doc()` writes `state="live"`. Stored artifact states are `live` and
  `archived`.

## [0.1.2]

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

[Unreleased]: https://github.com/Agience/agience-prism-py/compare/v0.1.4...HEAD
[0.1.4]: https://github.com/Agience/agience-prism-py/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/Agience/agience-prism-py/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/Agience/agience-prism-py/releases/tag/v0.1.2
