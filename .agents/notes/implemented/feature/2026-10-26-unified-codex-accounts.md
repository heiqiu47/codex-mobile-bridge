# Agent Note: Unified local Codex accounts

Status: implemented

## Problem

Desktop and CLI already share saved Codex accounts, but two lists and an optional verification checkbox suggest independent identities.

## Decision

The UI shows one saved inventory and a separate API editor before reminders. It always verifies CLI configuration after a Desktop switch. With Desktop stopped, use the existing guarded CLI transaction without launching Desktop. Official login stays computer-only; Claude and remote environments keep their current scopes.

## Alternatives considered

Keeping both lists preserves existing controls but misrepresents one shared account home. Hiding the CLI list without retaining its API editor and model probes removes useful capability.

## Consequences

Desktop and CLI may report different success outcomes; retain partial-success reporting. The [previous optional-sync decision](../../implemented/feature/2026-10-14-local-cli-account-sync.md) partially overlaps and remains as historical rationale. Active account-sync and WSL notes remain applicable outside this narrow local Codex decision.

Targeted account UI, CLI editor, WSL scoping and backend account/sync/access fixtures verify this behavior. No personal account switch or model request is performed.

The [account presentation and platform scope correction](../bug-fix/2026-10-26-account-ui-and-platform-scope.md) supersedes the desktop editor placement and skips WSL initialization on unsupported gateways; the account inventory and endpoint identity contracts remain.
