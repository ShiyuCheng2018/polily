# scanner/tui/theme.py
"""v0.8.0 Polily brand themes.

Registered at App startup alongside Textual's built-in themes. User can
switch via Ctrl+P → Change theme.

Themes:
- `polily-dark` — default: GitHub-dark-inspired palette with amber/blue
  accents. Balanced, general-purpose.
- `polily-geek` — phosphor-green terminal aesthetic (see
  docs/internal/architecture-metaphor-icu.html for reference):
    * Pure black background, dark green panels
    * Phosphor green primary + bright green highlights
    * White neutral for "human" content
    * Amber warning + red error retain functional color semantics
"""
from textual.theme import Theme

POLILY_DARK = Theme(
    name="polily-dark",
    primary="#4A9EFF",
    secondary="#8A9DB5",
    accent="#FFB84A",
    background="#0D1117",
    surface="#161B22",
    panel="#1F2937",
    success="#3FB950",
    warning="#D29922",
    error="#F85149",
    foreground="#E6EDF3",
    dark=True,
    variables={
        "text-muted": "#8B949E",
        "text-disabled": "#484F58",
        "tier-a": "#F0B85F",
        "tier-b": "#A6ADB5",
        "tier-c": "#B08D57",
    },
)

POLILY_GEEK = Theme(
    name="polily-geek",
    # Phosphor-green terminal aesthetic.
    primary="#33FF66",         # phosphor green (brand)
    secondary="#7FFF9F",       # bright green highlights
    accent="#F0F0F0",          # white — "human" accent
    background="#000000",      # pure black CRT
    surface="#050A05",         # near-black panel
    panel="#0F2A0F",           # dark-green tinted card
    success="#33FF66",         # on-brand — completed = primary green
    warning="#FFCC33",         # amber (terminal classic)
    error="#FF3366",           # hot pink/red — readable against green
    foreground="#F0F0F0",
    dark=True,
    variables={
        "text-muted": "#909090",       # white-dim
        "text-disabled": "#606060",
        "tier-a": "#7FFF9F",           # bright green → top tier
        "tier-b": "#909090",           # white-dim → middle
        "tier-c": "#1A7A33",           # green-dim → bottom
    },
)


def register_polily_theme(app) -> None:
    """Register all Polily brand themes on the given App.

    polily-dark is set as the default; users can switch to polily-geek
    (or any built-in Textual theme) via Ctrl+P → Change theme.
    """
    app.register_theme(POLILY_DARK)
    app.register_theme(POLILY_GEEK)
    app.theme = "polily-dark"
