# Agent Note: Copy native session identity

Status: implemented

## Problem

Sharing a chat requires its original client identity without activating or cloning it.

## Decision

The side-effect-free BridgeSessionLinks.text helper returns a Codex thread URL with the native SSH hostId, or the original Harness Session ID. It returns null for unsupported providers, invalid Codex IDs, and WSL endpoint digests. Detail actions use BridgeClipboard, including its HTTP and manual-copy fallbacks. Codex title details place the copy action beside the execution host, separate from message management and rename. Harness details expose the original native Session ID.

Known copy controls keep the legacy `message-copy` class: already-published iOS and Android injections accept trusted clicks only on `message-copy` or `code-copy`, then consume the click once. They override `BridgeClipboard.copy`, so changing only a new mobile bundle cannot repair existing apps. The shared `copyWithFeedback` adapter calls that override and notifies only after a browser acknowledgement or the old native hook has requested text, reported no failure and set its acknowledged success label. It never treats a prior success label or a silent rejected click as a new acknowledgement. Browser manual-copy fallback notifies only after its later successful retry. Native rejection still uses the existing visible error event; token, frame, origin, foreground and trusted-click checks are unchanged.

## Alternatives considered

Using every Bridge host as Desktop hostId makes WSL links look valid even though the endpoint is an internal registry digest. The helper therefore refuses that identity. Launching the Desktop URL would open a session rather than copy it.

## Consequences

Copying does not activate or modify a session. Native WSL Desktop mapping remains unsupported. tests/session-links.test.cjs verifies native identity and unsupported cases; existing clipboard tests cover copy fallbacks. `tests/mobile-copy-compat.test.cjs` executes an immutable v2.1.5 shared-injection fixture (byte-identical to v2.1.4) for both iOS and Android against the actual link, file/folder and Harness actions, including native rejection and stale-label cases. Active notes searched for clipboard, deep links and session identity contain no existing link decision; WSL unified architecture partially overlaps identity boundaries and remains unchanged.
