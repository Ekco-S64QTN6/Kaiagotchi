# Maintainer Progress

## Run 2026-11-09 22:43 UTC

**HEAD at start:** d6c91ebb1692e7d87bd49aa8683098d8d5dc1fd8
**HEAD at end:** d6c91ebb1692e7d87bd49aa8683098d8d5dc1fd8 (code baseline before this run's pending PR merge; this handoff is included in PR #152)
**Batches landed this run:** 1 pending final merge of #152

### Merged
- #149 — Require token authentication for non-loopback Cyber-Deck HUD access; protect the index, HTTP telemetry, and WebSocket while preserving loopback defaults.
- #150 — Return detached, synchronized Epoch snapshots and detach caller-owned network input.
- #151 — Synchronize shared PersistentMood state and saves; serialize writes and restrict the state file to owner permissions.

### Issues closed
- None. Phase 0 found zero open issues; no issue was closed without a verifiable fix.

### Issues filed
- None.

### Docs updated
- CHANGELOG.md — Unreleased entries for the HUD auth, Epoch snapshot, PersistentMood synchronization, and Epoch observation validation batches.
- ROADMAP.md — Records each completed reliability/security batch.
- CONTRIBUTING.md — Documents synthetic test expectations and shared persistence/observation contracts.
- PROGRESS.md — This handoff.

### In progress / blocked (pick up here next run)
- PR #152 — `fix/epoch-observation-input-validation-2026-11-09`; hostile review complete, exact-head CI green at `ff03ac88a7128428605f08320e6a42e3cfd4c7fb`; merge is the immediate next action.
- Branch `fix/tui-thread-failure-shutdown-2026-11-09` — its three-commit delta is already contained in merged PR #142; stale orphan branch only. The available GitHub connection exposes no branch-delete action, so deletion requires a GitHub UI/CLI session with repository ref deletion permission.
- Full local `ruff check .`, `mypy .`, and `pytest -q` baseline — not executable through the connected GitHub-only tools in this session. Exact-head GitHub Actions gates have been checked instead; do not represent CI as a local run.

### Deferred findings (filed as issues)
- None yet. Continue the package-wide review before concluding there are no further findings.

### Baseline for next run
- ruff: clean on main CI (blocking job passed).
- mypy: zero reported errors on main CI (blocking job passed).
- pytest: Python 3.11, 3.12, and 3.13 suites passed on main CI; exact pass counts are not exposed by the summary API.
- CI on main: green at `d6c91ebb1692e7d87bd49aa8683098d8d5dc1fd8` (run 42713634764).

### Recommended first action next run
- Verify the post-merge main workflow for #152, then continue the repository sweep across config/core/network/UI/plugins and clean up the stale #142 branch when ref-delete access is available.

## Run 2026-11-09 22:51 UTC

**HEAD at start:** d6c91ebb1692e7d87bd49aa8683098d8d5dc1fd8
**HEAD at end:** 6293bad76e02927e1a1055a2d9007269680c004e (merged code batches #152 and #153; docs-only batch is on the branch below)
**Batches landed this run:** 2

### Merged
- #152 — Normalize Epoch observation channel IDs, safely handle malformed AP/peer values, and guard invalid bond-encounter scaling.
- #153 — Make custom `PluginManager(plugin_dir=...)` roots load their own package contents and relative imports; replace mocked discovery with a real external package fixture.

### Issues closed
- None. Phase 0 found zero open issues.

### Issues filed
- None yet. The remaining placeholder utility findings are being assessed for scope and appropriate deprecation/implementation path before filing.

### Docs updated
- PR #152: `CHANGELOG.md`, `ROADMAP.md`, `CONTRIBUTING.md`, and new root `PROGRESS.md`.
- PR #153: `README.md` plugin discovery section, `CHANGELOG.md`, `ROADMAP.md`, and `CONTRIBUTING.md`.
- Pending docs batch: `README.md` passive-only monitor-mode requirement and LAN token/launcher environment caveat; `requirements.txt` all-extras install example now includes `fuzz`; `CHANGELOG.md`, `ROADMAP.md`, and `CONTRIBUTING.md` updated accordingly.
- This handoff section appended; previous run history retained.

### In progress / blocked (pick up here next run)
- Docs branch `docs/passive-capture-prereqs-and-extras-2026-11-09`, head `f012598e1e7459ebe365deb19247759511e41b85`; documentation review complete, PR to be opened and exact-head CI verified before merge.
- Branch `fix/tui-thread-failure-shutdown-2026-11-09` is stale: all three commits are already included in merged PR #142. It cannot be deleted using the currently exposed GitHub actions because no ref-delete operation is available; remove it with an authorized GitHub UI/CLI session.
- Local `ruff check .`, `mypy .`, and `pytest -q` cannot be executed through the connected GitHub-only tools. Exact-head hosted CI is the verification source; no local run is claimed.
- Continue full package review. `kaiagotchi/core/utils.py` contains legacy `iface_channels()` and `extract_from_pcap()` placeholders, and `kaiagotchi/network/utils.py` contains another hard-coded `iface_channels()`; no internal call sites were found in code search. Decide whether to add explicit deprecation/issue tracking or replace them with real supported implementations after a broader search.

### Deferred findings (filed as issues)
- None.

### Baseline for next run
- ruff: clean; exact-head blocking CI passed.
- mypy: zero errors; exact-head blocking CI passed.
- pytest: Python 3.11, 3.12, and 3.13 all passed on main CI; exact pass totals are not surfaced by the run summary.
- CI on main: green at `6293bad76e02927e1a1055a2d9007269680c004e` (run 42715093793).

### Recommended first action next run
- Finish and merge the passive-capture/docs truth-up PR, then review/deprecate the unused placeholder utility APIs and continue the codebase sweep.


## Run 2026-11-09 22:53 UTC — Phase 9 update

**Latest merged main:** `6293bad76e02927e1a1055a2d9007269680c004e`
**Docs batch:** PR #154, `docs/passive-capture-prereqs-and-extras-2026-11-09`; documentation changes are committed through `4fda73c357592ae0cf5a819b48229070ac964cd8`, and this appended handoff update is included in the same PR.

### Additional docs verification
- Confirmed `run_kaiagotchi.sh` allowlists only `KAIAGOTCHI_INTERFACE` and `KAIA_CONFIG` through sudo; the Web HUD token should be placed in a protected config file when using that wrapper.
- Confirmed pyproject extras are `dev`, `splash`, `net`, and `fuzz`; the `requirements.txt` all-extras example now names all four.
- Removed the stale `hcxpcapngtool` system-prerequisite comment; no source or launcher invocation uses that tool.
- Re-read the README hardware/auth/plugin passages and the changed requirements, CHANGELOG, ROADMAP, and CONTRIBUTING text against the implementation.

### Current blocker
- PR #154 is open and must pass its exact-head CI before merge. Do not merge while checks are queued, running, or red.
- Stale branch `fix/tui-thread-failure-shutdown-2026-11-09` still only contains the already-merged PR #142 changes; ref deletion is unavailable through this connection.

### Recommended first action
- Check PR #154's current head and all required checks, fix any failure, squash-merge only after green CI, then verify post-merge `main` CI and continue the placeholder-utility review.


## Run 2026-11-09 23:04 UTC — WebSocket session hardening

**HEAD at start:** `3fd015b040b38e7da7b7ba599ff92834ac0c3bc4`
**Code review finding:** active WebSockets were only authenticated at handshake; logout revoked HTTP sessions but did not close existing sockets, and expiry was not rechecked on subsequent broadcasts.

### Issues filed
- #155 — Stop `core.utils.extract_from_pcap()` from returning fabricated positive handshake data; labeled `bug`.
- #156 — Replace the duplicate hard-coded `iface_channels()` placeholders with capability-aware behavior or a documented deprecation path; labeled `bug`.

### In progress
- Branch `fix/websocket-session-revocation-2026-11-09`: associate each active WebSocket with its authorizing session, enforce session validity for incoming actions and periodic broadcasts, and close sockets immediately on logout/expiry. Synthetic integration tests cover logout revocation, idle expiry, and expired state requests.
- `README.md`, `CHANGELOG.md`, `ROADMAP.md`, and `CONTRIBUTING.md` updated to describe and test the session revocation contract.
- #154 is merged at `3fd015b040b38e7da7b7ba599ff92834ac0c3bc4`; post-merge main CI run 42716073379 passed all five jobs.

### Baseline and blockers
- Main CI at `3fd015b040b38e7da7b7ba599ff92834ac0c3bc4` is green (run 42716073379).
- Open issues now include #155 and #156; both are labeled `bug` and have explicit acceptance criteria.
- No open PR existed at the start of this batch.
- Local `ruff`, `mypy`, and `pytest` remain unavailable through the connected GitHub-only tools; use exact-head Actions and do not claim a local run.
- Stale `fix/tui-thread-failure-shutdown-2026-11-09` still contains only changes already merged by #142; branch deletion remains blocked by the missing ref-delete capability.

### Recommended first action
- Open/verify the WebSocket session-revocation PR, repair any exact-head CI failure, and merge only after all required jobs pass. Then verify post-merge main CI and continue the source review with issues #155 and #156 in the backlog.
