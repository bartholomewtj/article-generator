# Project Rules & Guidelines

## Iframe & Sub-template Theme Alignment
Always align default `:root` CSS variables in sub-templates or iframe templates with the primary application's default theme (e.g., dark mode default `--bg: #0f1115; --ink: #f1f5f9;`). Additionally, apply explicit `color: var(--ink)` rules across all text elements (`p`, `h2`, `h3`, `li`, `blockquote`, `aside`) rather than relying on body inheritance alone.

## Password Manager Heuristics Suppression
When adding API key, token, or secret inputs (`type="password"` or `type="text"`) alongside normal text fields:
- Use `autocomplete="new-password"` or `autocomplete="off"`
- Add vendor-specific suppression attributes: `data-1p-ignore="true"`, `data-lpignore="true"`, and `data-bwignore="true"`
- Wrap setting modal fields in `<form autocomplete="off" onsubmit="return false;">` to prevent unwanted browser password save dialogs.
