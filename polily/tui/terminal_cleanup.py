"""Terminal cleanup before os._exit() — fixes Bug R5-B.

polily TUI cannot use Textual's normal shutdown path because `claude -p`
spawns Node.js subprocesses that survive sys.exit / atexit handlers.
The only reliable termination is `os._exit(0)`, but `os._exit` skips
ALL Python cleanup including Textual's driver `stop_application_mode`.

If we exit while xterm mouse-tracking modes (?1000/1002/1003/1006/1015)
or alt-screen (?1049) are still active, the user's parent terminal
remains in those modes and starts spewing raw `\\x1b[<N;X;Y;M` SGR
mouse-event sequences as visible text on every mouse move/scroll —
broken until the user runs `reset(1)`.

`cleanup_terminal(app)` is the single safe pre-`os._exit` step. Every
`os._exit` site in `polily.tui.*` calls it first.

Two strategies, in priority order:

1. **Canonical** — call `app._driver.stop_application_mode()`. This is
   the same private API Textual itself uses on normal exit, so it
   restores whatever modes the driver enabled (matches Textual's own
   tracking, no risk of disabling something we never enabled).

2. **Fallback** — if no app/driver is reachable (FatalConfigScreen
   exits the early `_FatalApp` before PolilyApp is constructed), write
   the explicit DECRST sequences directly to stdout. The set covers
   every mouse-tracking mode polily TUI is known to enable plus the
   common alt-screen/cursor-show pair Textual itself toggles.

Both paths are wrapped in `contextlib.suppress(Exception)` because we
are about to `os._exit` — never let cleanup itself raise. A leaked
exception here would print a stack trace right before exit and still
leave the terminal corrupted; the silent fallback is strictly better.
"""

from __future__ import annotations

import contextlib
import sys
from typing import Any, TextIO

# Mode-disable sequences we emit when no driver is reachable.
# Order is intentional: mouse modes first (most likely culprit per the
# real R5-B repro), then cursor/alt-screen.
_FALLBACK_RESTORE = (
    "\x1b[?1000l"  # X10 mouse off
    "\x1b[?1002l"  # button-event mouse off
    "\x1b[?1003l"  # all-motion mouse off
    "\x1b[?1006l"  # SGR extended mouse off
    "\x1b[?1015l"  # urxvt extended mouse off
    "\x1b[?25h"    # show cursor
    "\x1b[?1049l"  # leave alt-screen (back to user's primary buffer)
)


def cleanup_terminal(
    app: Any | None = None,
    *,
    stream: TextIO | None = None,
) -> None:
    """Restore terminal modes before os._exit().

    Args:
        app: A Textual `App` instance, or None. If `app._driver` is
            reachable and exposes `stop_application_mode`, that path is
            taken (canonical). Otherwise we fall back to writing
            DECRST sequences to `stream`.
        stream: Output for the fallback path. Defaults to sys.stdout.
            Tests inject a buffer; production callers leave this None.

    Never raises — wrapped in suppress(Exception) end-to-end so an
    error here cannot prevent `os._exit` from running on the line below.
    """
    driver = None
    with contextlib.suppress(Exception):
        driver = getattr(app, "_driver", None) if app is not None else None

    if driver is not None:
        with contextlib.suppress(Exception):
            driver.stop_application_mode()
            return

    out = stream if stream is not None else sys.stdout
    with contextlib.suppress(Exception):
        out.write(_FALLBACK_RESTORE)
        out.flush()
