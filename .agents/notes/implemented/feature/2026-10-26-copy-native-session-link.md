# Agent Note: Copy native session identity

Status: implemented

## Problem

Sharing a chat requires its original client identity without activating or cloning it.

## Decision

The side-effect-free BridgeSessionLinks.text helper returns a Codex thread URL with the native SSH hostId, or the original Harness Session ID. It returns null for unsupported providers, invalid Codex IDs, and WSL endpoint digests. Detail actions use BridgeClipboard, including its HTTP and manual-copy fallbacks.

## Alternatives considered

Using every Bridge host as Desktop hostId makes WSL links look valid even though the endpoint is an internal registry digest. The helper therefore refuses that identity. Launching the Desktop URL would open a session rather than copy it.

## Consequences

Copying does not activate or modify a session. Native WSL Desktop mapping remains unsupported. tests/session-links.test.cjs verifies native identity and unsupported cases; existing clipboard tests cover copy fallbacks. Active notes searched for clipboard, deep links and session identity contain no existing link decision; WSL unified architecture partially overlaps identity boundaries and remains unchanged.
