# Terminal dependencies

Vendored from the npm registry with SHA-512 integrity verification.

- @xterm/xterm 5.5.0 (MIT)
- @xterm/addon-fit 0.10.0 (MIT)

Original license texts are included alongside the assets.

The vendored `xterm.js` has two local edits in its DOM renderer: the dimension
and theme `<style>` elements take the nonce from the page's
`meta[name="bridge-style-nonce"]` before insertion. Keep these edits when
updating the vendored package so terminal font sizing, ANSI colors, and cursor
styles work under the page's CSP.
