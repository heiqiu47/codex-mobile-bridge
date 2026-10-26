# Agent Note: Proxy HTTP startup backlog and GET framing

Status: implemented

## Problem

A reverse proxy can open many upstream HTTP/1.1 sockets while loading a cold page. A small listen backlog rejects connections before handlers run. Separately, an empty chunked GET leaves framing bytes unread; persistent request parsing can interpret those bytes as the next request. These are different transport failures and require separate checks.

## Decision

`GatewayServer.request_queue_size` is explicitly 128. This is the pending TCP listen backlog, subject to operating-system limits, and does not increase accepted handler concurrency. All listeners retain the existing shared 48-slot semaphore and 20-second connection timeout. Local CPython 3.12 uses a default backlog of 5; newer CPython defaults can differ, so 128 is an explicit target rather than a universal increase over every Python release.

GET processing does not consume request bodies. Before dispatch, the handler marks the connection for closure if any `Transfer-Encoding` header exists, even when empty, or any `Content-Length` value after whitespace trimming is not exactly `0`. The normal resource/API response still follows the existing route checks. The handler then closes without parsing residual body/framing bytes as another request. Ordinary bodyless GETs and canonical zero-length GETs keep connection reuse.

Authentication, exact Host/Origin pairing, CSRF checks, active-connection admission, session mutation routing and JSON/upload framing validation are unchanged. POST still rejects chunked JSON bodies, duplicate lengths and invalid lengths. A GET body containing a syntactically valid, authenticated pin/archive POST cannot dispatch that mutation on the same connection. This is a framing boundary, not a replacement for authorization.

## Existing-note audit

No active note covers the listen backlog or unread GET framing. [Bridge session management](../../implemented/feature/2026-10-26-bridge-session-management.md) partially overlaps only in authenticated pin/archive route boundaries; that decision remains in force. The existing architecture security section documents the transport policy. No prior decision needs rejection or removal.

## Alternatives considered

- Increase accepted handler concurrency: may reduce resets under load, but changes the resource and security budget rather than the pending connection queue.
- Drain GET bodies: preserves upstream pooling, but requires bounded framing parsing and read-time limits. Closing the affected connection is the smaller fix for a gateway that does not accept GET bodies.
- Disable keep-alive for all GETs: avoids residual bodies but needlessly loses pooling for ordinary bodyless resources.

## Testing

The seven loopback proxy tests validate a 38-connection pending startup burst, the unchanged 48-slot accepted-connection limit, normal GET reuse, empty/chunked/invalid/duplicate-length GET closure, and rejected chunked writes. Added regressions put valid authenticated pin/archive POST bytes directly inside a framed GET body and assert no mutation dispatch and EOF. Separate authenticated POST cases exercise missing login, missing CSRF, wrong Origin, chunked encoding, duplicate/invalid lengths and successful single dispatch.

Bounded in-process old-behavior overrides reproduce both failures without editing product source: backlog 5 times out within the fixture's two-second connect limit; the old GET handler dispatches three synthetic pin calls and three archive calls from unread GET bodies. The patched seven-test suite passes. These expected pre-change failures are separate from regression results.

The requested existing auth, login-security, Bridge, session-management and Python resource suites pass: 157 tests, two platform skips. Node asset/relay checks pass: four tests. All sessions and native-operation targets are synthetic; no real proxy deployment, desktop process, account, chat, installation or model call is exercised by these tests.

## Consequences

Cold proxy startup can queue the intended burst without raising the active connection budget. Framed GETs cannot leave bytes for a subsequent HTTP request. Affected upstream sockets reconnect instead of being pooled; ordinary resource GETs retain reuse. A larger backlog does not guarantee more than 48 accepted connections or solve saturation by long-lived connections. Real proxy acceptance remains a separate deployment check. Existing binary/304 response helpers can omit an explicit close header but still close the socket; this change does not broaden their response behavior or alter protocol upgrades.
