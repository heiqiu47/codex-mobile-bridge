# Agent Note: Confirmed stop, release and archive

Status: implemented

## Problem

Disconnecting a Bridge reader does not release a native writer. Users explicitly request stopping the selected chat before archive, with a confirmation dialog whose left button is Confirm archive and right button is Cancel. A failed stop must not cause an archive or be replayed as a new stop after reconnect.

## Decision

An explicit `disconnect:true` on an archive request opts into stopping the exact original target and its verified descendants. Older requests retain idle-only semantics; restore never stops work. The existing lifecycle gates exclude new Bridge submissions during the operation. Persist the existing unknown receipt before any stop or release, read fresh native state after stopping, and only then archive through the original runtime. Never close a shared application/daemon or kill unrelated processes to release one chat. Uncontrollable native owners remain a clear failure, not a fabricated success.

The confirmation displays title, execution host and interruption consequences. Confirm archive is on the left, Cancel on the right and initially focused. Both buttons use the same existing primary style and equal grid columns; phone-width visual acceptance prevents a narrow/wrapped Cancel label. Cancel, Escape and dismissal perform no request. Restore retains its separate action.

## Existing-note audit

- [Native archive feedback](../../implemented/bug-fix/2026-10-26-native-session-archive-feedback.md): partially superseded only for explicitly confirmed stopping; original-owner, reversible storage and uncertain-write requirements remain.
- [Bridge session management](../../implemented/feature/2026-10-26-bridge-session-management.md): overlapping routing, identities and receipts remain in force.
- Local-first pin notes remain unrelated: stopping and archive never enter their retry queue.
- No other active proposed/rejected archive decision supersedes this request.

## Alternatives considered

Merely disconnecting Bridge leaves native writers alive. Exiting the whole desktop app releases writers but affects unrelated chats. Editing Codex storage bypasses native ownership. Direct native archive through the actual owner avoids unnecessary detach/reattach when supported; releasing a per-chat Claude executor is needed before file-level archive.

## Verification contract

Dialog order and cancellation are exercised through the real event handlers. New synthetic native sessions demonstrate targeted stop/archive/restore while an unrelated session remains usable. Unknown stop/archive results are never replayed. Unsupported external owners are refused without stopping the whole app. Existing idle-only and restore callers retain their behavior.

## Consequences

Native client capabilities differ by version; a connected App follower is not its execution owner. Approval covers dedicated new test sessions only, not stopping existing user work. No whole-app shutdown, credential change or release publishing is part of this change.

## Provider behavior

Codex CLI and WSL stop verified current turns through their original runtime, clear only that subtree's background terminals, re-read idle state and the descendant inventory, then call native archive without restarting/resuming the target. A `notLoaded` thread is not queried for background terminals (the installed runtime rejects that call) or loaded just for archival. A changed original control connection or child scope prevents archive. New uncertain receipts retain the complete pre-operation archive scope: a partially archived subtree cannot be reported or reconciled as confirmed merely because its root archived.

Claude Code Desktop uses its existing native interrupt on the verified running subtree, polls fresh native activity and then archives with `cleanupWorktree:false`. Connector revision 12 prevents an old injected implementation silently accepting the new behavior. Unresolved background work, queued input, unknown descendants and pending native mutations still prevent archive. Cowork does not gain unsupported archive/restore capability.

Owned Claude CLI/SSH/WSL executors acknowledge native interrupt, wait for result/pending-request settlement, close stdin and wait for process exit before the existing profile, version, registry and executable-census checks. There is no terminate/kill fallback. Installed CLI 2.1.292 emits a final `error_during_execution` result and exit code 1 after acknowledged user interruption; this specific active-stop exit is accepted, while timeout and signal/other abnormal exits prevent archive. File-level archive and restoration remain reversible and preserve the original native ID and bytes. The remote archive-state read may report unsafe without stopping anything; the remote mutation still requires all original writer checks.

DSH uses the native `workspace/session-stop` providers for the selected session's turn, descendants, jobs and schedules, then verifies `workspace/session-activity`, current running state and pending questions before native `archiveSession(sid,{})`. The installed registry's `stopActivity:true` persists the archive before requesting stops and swallows stop failures; it was rejected for this stop-before-archive contract. Native default admission still guards the final write. Bridge revision 7 distinguishes this contract from the previously loaded idle-only implementation. The verified revision 6 LF and CRLF source hashes remain recognized: discovery reuses the original transport, source location, credentials and receipts without rewriting a live plugin; upgrading the native plugin retains the existing explicit restart and fresh task-state gate. Unknown source hashes remain rejected. Reconnecting or starting the gateway with an older running DSH host only records restart-required; it never exits the host or updates its loaded source. Only the explicit restart action can use the fresh idle gate and replace that source. This boundary corrects the pre-existing reconnect path that otherwise upgraded and restarted a running host during Test startup.

## Verification and limits

- Release cross-platform validation separates real POSIX archive storage tests from portable process/dispatch contracts. Windows native Claude archival remains disabled and has an explicit negative test; POSIX fsync/ownership round-trips run on Mac/Linux rather than mocking a successful Windows archive. Synthetic process census fixtures provide getuid explicitly and compare path components independently of the runner. The standalone remote-worker fixture executes its exact generated payload from a temporary file, avoiding the Windows command-line length ceiling while still running without Bridge imports.

- DSH migration follow-up: 51 targeted Python tests and 6 native-provider Node tests passed. The subsequent no-implicit-restart correction passes all 54 DSH migration/recovery tests. The WSL-specific lifecycle fixture explicitly supplies both Windows registries while the default macOS fixture remains free of WSL initialization; all 151 lifecycle/migration/recovery tests pass. Release preparation runs 2,671 backend source tests with 47 documented platform/native-fixture skips and no failures, plus 1,206 frontend passes and one platform skip. The installed revision 6 connector is recognized read-only with no configuration writes; explicit-upgrade fixtures retain its original credentials, receipts and insertion.
- Frontend: 1,206 passed, one existing skipped test. Confirmation handlers verify left Confirm archive/right Cancel, default Cancel focus, no request on cancel/dismissal, exact host/provider identity, and restore without stopping. Actual connector/host fixture tests verify stop ordering, target-only scope and failure before archival.
- Backend: 185 targeted tests passed before the final original-connection guard; 29 focused archive tests passed after that guard. Coverage includes HTTP auth/CSRF and flag validation, full-subtree receipts, no replay after unknown stop, owned CLI exit semantics, real synthetic file archive/restore, remote identity and WSL routing. Three existing remote archive tests had been accidentally nested below `unittest.main()`; they are now discovered and run.
- Installed Codex 0.164.0-alpha.11.1: isolated home plus fake loopback Responses streaming, no account credentials. Two new native sessions actively streamed. Production stop helper stopped only the target; same-runtime archive and restore retained its ID; the second session remained active until explicit test cleanup. A concurrent second runtime was refused by the original writer lock. A restored/unloaded session passed the new preflight without being resumed. Evidence is under the ignored `.tmp/disconnect-archive-20261027/codex-native/`.
- Installed Claude 2.1.292: a new isolated, sandboxed CLI with fake loopback inference acknowledged interrupt, emitted its final result, consumed EOF and exited with code 1. Real user files, keychain and external networking stayed forbidden. The subsequent production executable census found another existing Claude CLI and correctly prevented file archival; no unrelated process was stopped. Therefore this run proves native release and the writer refusal, not a completed live Claude archive round-trip. Synthetic adapter/file tests cover the remaining ordering and restore path.
- Actual Windows/WSL/Linux process acceptance and live Claude Code Desktop/DSH archive acceptance were not run in this change. Those paths have contract regression coverage, not new platform-native evidence.
- Loaded Codex App sessions remain an explicit limitation. Installed App 26.1021.31345 exposes follower interrupt but no verified follower archive/unload operation. Removing Bridge's follower cannot release the App's own writer. The implementation does not stop a desktop turn that it cannot subsequently release, quit a shared App, forge archive broadcasts or edit native storage. Writer-free App history retains the earlier supported native archive path. This change does not justify a claim of universal App/CLI archive support or closing that remaining issue.

## Branch cleanup

User-approved remote and local `release/v2.1.4-preview.1` (4c251de061da073c6138780d2c9a3a868ea123c5) and `release/v2.1.0-preview.1` (422a46b6ae90b0c52748894c387741ce346ebb92) were deleted after fresh main ancestry and worktree-occupancy checks. Remote deletion used atomic, exact expected-head leases. Tags and Releases were retained. No v2.1.6 release or tag was published.
