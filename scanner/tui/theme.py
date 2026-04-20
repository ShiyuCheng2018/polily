# scanner/tui/theme.py
"""v0.8.0 Polily brand theme.

Registered at App startup alongside Textual's built-in themes. User can
switch via Ctrl+P → Change theme.
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


def register_polily_theme(app) -> None:
    """Register polily-dark theme on the given App and set it as default."""
    app.register_theme(POLILY_DARK)
    app.theme = "polily-dark"
