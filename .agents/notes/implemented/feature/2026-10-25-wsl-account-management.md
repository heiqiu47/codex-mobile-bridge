# Agent Note: Environment-scoped WSL account management

Status: implemented

## Problem

The gateway controls WSL Codex and Claude Code sessions but account management remains external-only for Codex and Desktop-scoped for Claude. Identical credentials copied from Windows do not establish shared configuration or continuous synchronization. Reusing the native Desktop switch would target the wrong environment and could disturb existing tasks and drafts.

## Decision

Use environment-scoped account management for registered WSL distribution/user/config-directory identities. Reuse the current account UI pattern and model-cache policy, with separate request routing and private target-side credential transactions. Preserve all existing native Desktop, local CLI and SSH paths. Reading an account must not start a distribution, daemon, thread or model request. Only explicit desktop enrollment/save/import and explicit authenticated switch may write the selected environment. Web/mobile retains its existing view/switch boundary.

Switch preflight checks current identity and actual runtime state, queued messages and unknown receipts. Unknown state blocks rather than clearing records, replaying messages or killing native processes. Atomic file updates preserve unrelated settings and history, recheck the expected identity and restore exact preimages only if no external writer changed them. Saved native credentials provide a return path; OS keyring or other unsupported credential sources are represented honestly rather than silently copied. Magpie and managed/overlapping profiles remain protected.

Model results and drafts remain bound to gateway/provider/environment/account identity. Cache reuse cannot authorize mutation. Secret-bearing requests use private stdin and owner-private files, and secrets never return in public snapshots or errors.

## Existing-note audit

- [Unified WSL endpoints](../architecture/2026-10-24-codex-wsl-unified.md): partially overlaps. Its environment identity, passive-read and lifecycle contracts remain. This decision supersedes only external-only account management for supported unmanaged WSL profiles; external tool protection remains.
- [Local CLI account synchronization](2026-10-14-local-cli-account-sync.md): partially overlaps, remains authoritative for native Windows/macOS/Linux and Desktop synchronization. WSL never inherits its native-local target by default.
- [SSH CLI model catalogs](2026-10-18-ssh-cli-model-catalog.md): partially overlaps on cache/identity and private transport; SSH configuration writes remain outside this change.
- Other matched CLI ownership, startup, history, model attribution and native session notes remain unchanged; they constrain runtime ownership but do not define WSL account writes. No note is fully absorbed or archived.

## Alternatives considered

- Reuse Desktop switching: reuses mature rollback/UI but writes Windows credentials and may restart Desktop for a Linux target. Keep separate routing.
- Automatically mirror Windows credentials: reduces repeated setup but makes account changes cross environments without explicit intent. Offer explicit import of a selected supported API profile instead.
- Keep all WSL accounts external-only: maximizes isolation but leaves a primary CLI management need unresolved. Retain external-only mode only when the profile cannot safely be managed.

## Consequences

The native Windows account panels, local CLI synchronization and SSH routing keep their existing transports. A new WSL panel and exact registered-target endpoints keep credentials out of the browser. This adds a target-side store and a small private worker; supporting further native auth schemes requires separate evidence rather than automatic fallback.

First-switch snapshots include the baseline identity in the same durable store write. If a failed write restores exact original files, another explicit user switch is possible. If rollback is incomplete or an external writer changes a file, the identity guard continues to block. No automatic retry is introduced.

Claude adds an optional `request_scopes` side table in the existing receipt transaction, only when a request is known to target WSL. Request IDs, fingerprints, statuses, confirmation and retry behavior remain unchanged. Historical unscoped receipts cannot be attributed from irreversible hashes; they stay intact and do not block every unrelated environment. Active or unattributed live processes still block. Future receipt changes must preserve this distinction.

API model discovery reuses the existing parser and TLS policy on the selected target. Cached results return before upstream I/O, with identity checks, singleflight and a 12-hour timer; stopped or disabled environments are not started. Failed refreshes retain only same-identity successful results. Network fetching does not hold registry or control locks. Closing the manager cancels timers and prevents both cached and inflight responses from being published.

Python 3.9/3.10 targets use vendored, unmodified MIT Tomli 2.0.1 source only when no TOML parser exists. Source is sent through stdin and loaded in memory, with no target package installation. License and source hashes are in `bridge/vendor/wsl_tomli/` and included in frozen resources.

Official login enrollment, keyring-backed credentials, managed profiles and unsupported custom provider routing remain in the original CLI. A configuration switch reports `activeVerified: false`: saving a file is not proof of upstream login validity. Existing chats, drafts and queues are not migrated to a new account.

## Verification

- Independent boundary tests cover same-target busy/unknown receipts, unrelated environment isolation, field/identity validation, import source races, exact rollback and external edits. Python 3.9 and 3.12 each pass the 46 worker, cache, source and boundary cases.
- Real HTTP tests cover authentication, CSRF, strict body fields, passwordless restrictions and rejection of browser secret management; original local account routes retain their contract.
- Native Windows-to-WSL execution uses Python 3.10.12 and tmpfs-only fake credentials. Codex and Claude file save/switch/exact restore pass; native Codex app-server reads the selected API route and auth type. Native Claude `auth status` recognizes the synthetic selected API and reports logged out for a separate empty profile, with outbound proxies disabled. Original credential/config file hashes are unchanged. No model or message is sent. These checks do not establish real upstream authentication.
- Browser fixtures exercise registered environment selection, stale response disposal, return to local panels, both languages and narrow/wide widths. Full frontend/backend suite results and frozen-package checks are recorded with the local candidate, not treated as installed-platform acceptance.
