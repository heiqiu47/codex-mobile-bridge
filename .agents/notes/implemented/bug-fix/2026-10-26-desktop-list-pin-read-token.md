# Agent Note: Successful client lists failed during pin synchronization

Status: implemented

## Problem

DSH and Claude successful nonempty list responses threw `ReferenceError: pinRead is not defined` when local pin preferences were enabled. The token was declared in `refresh()` but consumed inside the separate `refreshList()` method. Tests without a pin preference object bypassed argument evaluation through optional chaining, missing this production path. Repeated automatic failures exposed the retry banner even though the connector returned a connected list.

## Decision

Capture the pin read token on the shared list task when the request starts, and consume that same token while observing rows. Polling, manual refresh and prefetched reads share the request token. A local pin change after prefetch must not make the earlier response look newer.

## Existing-note audit

[Local first pins](../feature/2026-10-26-local-first-session-pins.md) defines the token and stale-read contract; this repairs its cross-method integration. [Shared list refresh](../feature/2026-10-12-shared-client-list-refresh.md) defines request sharing and failure feedback; its genuine disconnect/error behavior is retained. Neither existing note describes this missing variable integration failure.

## Alternatives considered

Suppressing the retry banner would conceal genuine network failures. Capturing the token only when a view joins an existing request would misdate prefetched responses. Replacing connector polling does not address the reproduced frontend exception.

## Testing

Before the fix, connected list fixtures with pin preferences reproduced the exact ReferenceError for both providers. Four regression cases cover normal and prefetched requests for both providers. Related UI tests: 220 passed. Full frontend: 1204 passed, one skipped. No real session, pin, message or archive mutation was used.

## Consequences

Successful reads update the list and clear failure state normally. Genuine connector errors continue to produce retry feedback. The reproduction establishes a concrete frontend cause; it does not rule out separate network failures.
