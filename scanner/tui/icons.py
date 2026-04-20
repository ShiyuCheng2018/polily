# scanner/tui/icons.py
"""v0.8.0 Nerd Font icon glyphs — semantic names mapped to NF codepoints.

All icons use Nerd Font Awesome Legacy codepoints (U+F000 range). Works with
JetBrains Mono Nerd Font, FiraCode NF, Hack NF, MesloLG NF.

Codepoint review: all values below verified against
https://github.com/ryanoasis/nerd-fonts/blob/master/glyphnames.json
(Font Awesome Legacy mapping, as of Nerd Fonts v3.x).
"""

# Domain entities
ICON_EVENT = "\uf073"       # fa-calendar
ICON_MARKET = "\uf080"      # fa-bar-chart-o
ICON_WALLET = "\uf0d6"      # fa-money
ICON_POSITION = "\uf0b1"    # fa-briefcase (for "held position")

# Actions
ICON_SCAN = "\uf002"        # fa-search
ICON_BUY = "\uf067"         # fa-plus
ICON_SELL = "\uf068"        # fa-minus
ICON_SETTINGS = "\uf085"    # fa-cogs

# Status (scan_logs enum)
ICON_PENDING = "\uf017"     # fa-clock-o
ICON_RUNNING = "\uf021"     # fa-refresh
ICON_COMPLETED = "\uf00c"   # fa-check
ICON_FAILED = "\uf00d"      # fa-times
ICON_CANCELLED = "\uf05e"   # fa-ban
ICON_SUPERSEDED = "\uf079"  # fa-retweet (visually distinct from running — "replaced")

# Monitor state
ICON_AUTO_MONITOR = "\uf06e"  # fa-eye
ICON_NOTIFY = "\uf0f3"        # fa-bell


STATUS_ICONS = {
    "pending": ICON_PENDING,
    "running": ICON_RUNNING,
    "completed": ICON_COMPLETED,
    "failed": ICON_FAILED,
    "cancelled": ICON_CANCELLED,
    "superseded": ICON_SUPERSEDED,
}
