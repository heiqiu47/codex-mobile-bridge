# Agent Note: Hide the mobile native menu while web dialogs are open

Status: implemented

## Problem

The mobile hosts draw their native more menu above the WebView. A long Webhook settings dialog can scroll beneath it, leaving the background menu visible and tappable while the dialog is open. The host cannot infer HTML dialog state from the native view hierarchy.

## Decision

The shared mobile script observes the document for any `dialog[open]`. It sends a token-scoped `codexbridge-modal:` prompt with `open` when at least one dialog is open and `closed` when none remain. It sends only state transitions during normal DOM changes and resends current state when the page regains focus or visibility. The contract is based on dialog state, so dynamically inserted and future dialogs participate without host-side dialog IDs.

Android and iOS accept this signal only from the current WebView, the expected origin and the current token. The hosts hide and disable their native menu for `open`, then restore it for `closed`; navigation resets the menu state. The signal is transient UI state, not a setting. The [dialog backdrop dismissal note](../feature/2026-10-16-dialog-backdrop-dismissal.md) governs how a backdrop gesture closes an HTML dialog; this note governs the native overlay while any dialog remains open.

## Alternatives considered

Adding menu toggles to each Webhook dialog handler would be direct, but other and future dialogs would leave the same overlay bug. CSS cannot hide a native Android or iOS control outside the WebView. Observing the shared HTML dialog state keeps the boundary at the WebView-host contract.

## Consequences

Opening one or several dialogs makes the native menu unavailable until the last closes. Scrolling and internal DOM changes do not restore it. A focus return reconciles state if a prior signal was missed. The cross-process prompt adds a small amount of host handling; browser and source tests cover state transitions, but native device rendering requires a rebuilt app for verification.
