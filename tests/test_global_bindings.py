"""v0.8.0 Task 9: Q11 global bindings declared at App level."""
from scanner.tui.app import PolilyApp


def test_polily_app_declares_q11_global_bindings():
    bindings = {b.key: b.action for b in PolilyApp.BINDINGS}
    # Q11 mandates these global bindings:
    assert bindings.get("q") == "quit"
    assert bindings.get("question_mark") == "help" or bindings.get("?") == "help"
    assert bindings.get("escape") == "back" or bindings.get("escape") == "app.pop_screen"
    # ctrl+p is Textual's built-in command palette (theme switcher lives there)
    # We don't need to declare it explicitly — it's automatic
