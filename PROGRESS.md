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
- Branch `fix/websocket-session-revocation-2026-11-09`: associate each active WebSocket with its authorizing session, enforce session validity for incoming actions and periodic broadcasts, close sockets immediately on logout/expiry, and reject cross-origin logout. Synthetic integration tests cover logout revocation, idle expiry, and expired state requests.
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


## Run 2026-11-09 17:30 CDT — fabricated PCAP extraction fix

**Latest merged main at start:** `7066525126b36b880335e2587f933b50b89491e6`
**Prior batch:** PR #157 merged after exact-head workflow 42718222363 passed all five required jobs. Post-merge main workflow 42721091354 also passed all five jobs.
**Phase 0 at start:** 2 open issues (#155 and #156), 0 open PRs, only the known stale #142 branch plus main.

### In progress
- Branch `fix/extract-pcap-real-results-2026-11-09`: issue #155. `core.utils.extract_from_pcap()` now lazily delegates to `network.pcap_parser.parse_pcap()`, preserves its old dictionary keys, returns actual fields from the first parsed capture, distinguishes complete vs partial/PMKID data, and returns null identity / `handshake=False` / count 0 when there are no valid captures.
- New `tests/test_core_utils_pcap.py`: missing file, empty file, malformed input, truncated classic header, valid synthetic 802.11/EAPOL PCAP, and valid empty PCAPNG.
- `CHANGELOG.md`, `ROADMAP.md`, and `CONTRIBUTING.md` updated with implementation and test-contract notes.
- Local commands are not available through the connected GitHub-only interface; exact-head hosted CI is the merge gate. No local test run is claimed.

### Backlog
- #156 — duplicate hard-coded `iface_channels()` placeholders still need capability-aware behavior or a documented deprecation path.
- Stale branch `fix/tui-thread-failure-shutdown-2026-11-09` remains; its changes are already present via #142. The available GitHub operations have no ref-delete call.

### Next action
- Review this adapter/test diff, open a PR for issue #155, fix any exact-head CI failures, and merge only after Python 3.11–3.13 tests, compileall, Ruff, Mypy, and wheel/assets all pass. Then re-check issue #155 and post-merge `main` CI; continue with #156 as a separate batch.


## Run 2026-11-09 17:45 CDT — channel capability discovery

**Latest merged main at start:** 7def0ae48da9b0008019187563a21d37c109f578
**Completed prior batch:** PR #158 merged at 7def0ae; issue #155 closed as completed. Exact-head CI run 42721551057 passed all five jobs.
**Phase 0 at start:** issue #156 remained open; no open PRs; stale branch #142 only.

### In progress
- Branch fix/interface-channel-capability-query-2026-11-09: issue #156.
- kaiagotchi/network/utils.iface_channels() now resolves the selected interface's Wiphy through iw dev <interface> info, reads its reported frequency/channel entries through iw phy phy<N> info, removes entries explicitly marked disabled, and returns a sorted unique channel list.
- DFS and no-IR annotations remain included because those channels still matter for passive monitoring; no capability query failure falls back to a guessed static channel list.
- kaiagotchi/core/utils.iface_channels() now delegates to the shared network helper, removing the duplicate implementation.
- New synthetic tests cover Wiphy lookup, 2.4/5/6 GHz channel numbers, disabled channels, missing Wiphy, missing interface/PHY results, unavailable/timeout iw, invalid interface names, and legacy wrapper delegation.
- CHANGELOG, ROADMAP, CONTRIBUTING updated; progress handoff retained.

### Known compatibility limitation
- The legacy API returns channel numbers only, not band-qualified pairs. Identical numbers across 2.4 and 6 GHz therefore collapse to one value. A future typed API should expose (band, channel) or frequency if callers need unambiguous multi-band selection.

### Next action
- Review the implementation and tests, open the PR for #156, repair any exact-head CI failures, and merge only once all five required jobs pass. Then verify the post-merge main workflow, close #156, and re-run Phase 0 counters.


## Run 2026-11-09 17:55 CDT — InterfaceMonitor source merge

**Latest merged main at start:** 1714895946f0cea77bd7fb6aa87dc5763b6f0bae
**Phase 0 at start:** 0 open issues, 0 open PRs. Issue #155 and #156 are closed as completed. The only non-main branch is the stale #142 branch whose commits are already merged.
**Post-#159 main CI:** run 42722618670 passed all five required jobs.

### In progress
- Issue #160 — preserve InterfaceMonitor fields when merging ifconfig and ip snapshots.
- Branch fix/interface-monitor-source-merge-2026-11-09: changed _merge_interface_data() to merge interfaces, wireless_interfaces, and system_stats by key and merge nested fields. Later sources replace only conflicting individual fields; unrelated fields and distinct interfaces are retained.
- Tests added for same-interface source merging across all three maps, explicit later-source precedence on MTU, overall READY state, interface count, and different interfaces arriving from separate sources.
- CHANGELOG, ROADMAP, CONTRIBUTING, and method documentation updated.
- Local test execution is unavailable through this GitHub-only session; exact-head Actions remains the merge gate.

### Next action
- Hostile-review this merge behavior, open a PR for #160, pass all five exact-head CI jobs, then merge and close #160 only after verification. Re-check main CI and Phase 0 afterward.


## Run 2026-11-09 18:05 CDT — veth interface-name normalization

**Latest merged main at start:** 3f3e7397f3f654ea80a063fdea86c729bc57c977
**Post-#161 main CI:** run 42723242718 passed all five required jobs.
**Phase 0 before this finding:** 0 open issues and 0 open PRs; stale #142 branch only.

### In progress
- Issue #162 — normalize veth peer suffixes in iproute2 interface names.
- Branch fix/ip-addr-veth-interface-normalization-2026-11-09: _get_ip_addr_data() now removes only a trailing @if<number> annotation before using the local interface key.
- Synthetic tests cover two IPv4 addresses on one peer-annotated veth, a separate ordinary wlan interface, and merging the veth IP data with ifconfig metadata under one local name.
- CHANGELOG, ROADMAP, CONTRIBUTING updated.
- Local test execution remains unavailable through the GitHub-only connection; exact-head Actions is the verification gate.

### Next action
- Review the code/tests and PR, wait for Python 3.11–3.13, static-analysis, and wheel/assets checks, repair any failure, and merge only after green. Close #162 after merge and verify post-merge main CI.


## Run 2026-11-09 18:15 CDT — primary terminal typed-row hardening

**Latest merged main:** 4bc49ab1d2ba2de0868b972bfb0499a1c286c61a
**Previous batch:** PR #163 merged veth peer-suffix normalization; issue #162 directly verified closed. Exact-head workflow 42726012732 passed all five jobs. Post-merge main workflow 42726157283 also passed all five jobs.
**Phase 0:** 0 open PRs before this batch; 1 known stale branch fix/tui-thread-failure-shutdown-2026-11-09 (already merged via #142). New issue #164 filed for TUI typed-row compatibility.

### In progress
- Issue #164 — handle typed and malformed AP/station rows in the terminal renderer.
- Branch fix/tui-render-typed-network-records-2026-11-09.
- TerminalDisplay._take_snapshot() now filters non-dictionary AP/station rows before sorting/drawing and applies safe numeric coercion for sort keys; supplied _aps/_stas snapshots are filtered too.
- _draw_ap_rows() handles bool privacy (Secured/Open), preserves string encryption labels, uses essid with a typed-model ssid fallback, and safely stringifies nullable/non-string BSSID/channel/ESSID values.
- _draw_sta_rows() skips non-mappings and safely normalizes station MAC, packet count, and BSSID fields.
- New tests use AccessPoint.model_dump() plus a synthetic recording screen and cover malformed rows, null/non-string values, boolean privacy, and snapshot ordering.
- Scope is the mandatory terminal/TUI interface only. No Web HUD changes are included.
- CHANGELOG, ROADMAP, CONTRIBUTING updated. This handoff is appended to PROGRESS.
- Local pytest/Ruff/Mypy commands are not available through this GitHub-only connection; exact-head hosted Actions is the merge gate. No local run is claimed.

### Next action
- Review branch diff and tests, open PR #164, repair any exact-head CI issue, merge only when all five required jobs pass, close #164, and verify post-merge main CI. Then repeat Phase 0 and continue the next repository review.
