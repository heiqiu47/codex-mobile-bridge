# Agent Note: Account presentation and gateway platform scope

Status: implemented

## Problem

The unified account change split the desktop enrollment entry, while the phone editor lacks unsaved-draft model discovery. Desktop overview quota reads saved active rows but omits the native login card used by account management, and its hidden account panel can suppress quota loading. WSL controls and managers are initialized on gateways without WSL capability.

## Decision

The desktop restores the Add account or API entry and keep the unified saved inventory. The phone uses the user-approved compact grouped form with existing theme tokens. An explicit authenticated Codex draft-model request validates the original URL/key rules, queries the catalog without saving or switching, and never persists draft credentials. Empty model fields take the first returned ID; manual choices and newer edits win over late responses.

The desktop flattens only its provider heading rows. The gateway gates WSL-specific manager imports/initialization by the gateway operating system and loads account controls only from the gateway capability. Windows endpoint identity, native routing and write guards stay intact. Desktop overview uses the same native-login identity as account management and its existing visible-page quota cadence.

## Existing-note audit

- [Unified local accounts](../../implemented/feature/2026-10-26-unified-codex-accounts.md) partially overlaps: this supersedes its separate desktop editor placement, retaining inventory and switch verification.
- [WSL account management](../../implemented/feature/2026-10-25-wsl-account-management.md) and [WSL unified entry](../../implemented/architecture/2026-10-24-codex-wsl-unified.md) partially overlap: endpoint routing and credentials remain unchanged; unsupported hosts skip initialization.
- Claude manual-quota notes concern a separate provider and remain unchanged. No overlapping proposed/rejected account layout decision was found.

## Alternatives considered

Keeping separate desktop forms reuses the CLI editor but contradicts the requested original entry. Merely hiding WSL controls preserves eager loads and environment queries on unsupported systems. Reusing another saved account's quota fills the cell but misidentifies the current login; the native login card is the authoritative alternative.

## Testing

Targeted tests verify draft discovery without mutations, stale/manual edits, native unsaved-login quota, flat desktop rows and Windows versus non-Windows initialization. The actual grouped editor is inspected at 320 and 390 CSS pixels in both existing themes with synthetic data; it has no horizontal overflow. Only the root agent edits source and tests; build agents receive a frozen candidate.

## Consequences

An upstream catalog does not establish Responses compatibility. Missing quota remains explicitly unavailable rather than inferred. Lazy WSL loading must retain Windows behavior and report load failures without disturbing local accounts.

Repository-wide note validators still report pre-existing optimization folders and old note format failures; none of the changed notes is reported. Frontend regression: 1200 passed, one skipped. Account/platform/HTTP regression: 206 passed before additional platform lifecycle checks.

## User follow-up

The approved follow-up removes the outer compact disclosure style so the phone API entry uses the adjacent reminder disclosure typography. Group containers have no border; each field keeps a visible input boundary, persistent label and translated placeholder. Existing App theme tokens remain unchanged. The complete AccountsPanel nesting, rather than an isolated editor wrapper, is checked at 320/390px in light/dark themes.
