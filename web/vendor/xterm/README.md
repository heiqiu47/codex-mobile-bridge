# Terminal dependencies

Vendored from the npm registry with SHA-512 integrity verification.

- @xterm/xterm 5.5.0 (MIT)
- @xterm/addon-fit 0.10.0 (MIT)

Original license texts are included alongside the assets.

The vendored `xterm.js` has local edits in its DOM renderer: the dimension
and theme `<style>` elements take the nonce from the page's
`meta[name="bridge-style-nonce"]` before insertion. Keep these edits when
updating the vendored package so terminal font sizing, ANSI colors, and cursor
styles work under the page's CSP.

DOM text runs are positioned and sized by their buffer columns, including
double-width characters. This prevents browser font advances and rounding from
moving TUI background boundaries between rows. Block elements U+2580–U+2590,
U+2594 and U+2595 are drawn within their cells using foreground-color gradients;
their original text remains available for selection/accessibility. This avoids
font-baseline gaps in small OpenCode logos. `customGlyphs: false` retains font
rendering. Preserve these patches when updating; `tests/xterm-dom-grid.test.cjs`
executes the bundled row factory to cover grid positions and glyph boundaries.
