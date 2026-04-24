"""Version resolution tests.

After v0.9.3, `polily.__version__` is derived from package metadata
(installed distribution's `version` field), which in turn comes from
the git tag via `hatch-vcs`. There is no hardcoded version string
anywhere in the source tree — this is enforced by `test_no_hardcoded_version_literal_in_init`
and `test_no_hardcoded_version_literal_in_pyproject`.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

import polily

PEP440_REGEX = re.compile(
    # Core X.Y.Z, with optional .devN, .aN, .bN, .rcN, +local suffixes.
    r"^\d+(\.\d+)*((a|b|rc|\.dev|\.post)\d+)*(\+[a-zA-Z0-9.]+)?$"
)


def test_version_exists_and_non_empty():
    assert isinstance(polily.__version__, str)
    assert polily.__version__  # non-empty


def test_version_is_pep440_shape():
    assert PEP440_REGEX.match(polily.__version__), (
        f"polily.__version__={polily.__version__!r} does not match PEP 440 shape"
    )


def test_no_hardcoded_version_literal_in_init():
    """Source of polily/__init__.py must not contain a literal version string.

    Reject bare, f-string, r-string variants (`__version__ = "0.9.3"`,
    `__version__ = f"0.9.3"`, etc.). Dynamic resolution via
    `importlib.metadata` is the only acceptable pattern going forward.
    """
    source_path = Path(inspect.getfile(polily))
    source = source_path.read_text()
    # Reject any literal-string assignment to __version__ — including
    # f-string / raw-string prefixes.
    hardcoded = re.search(
        r"""__version__\s*=\s*[fFrRbB]?['"]\d+""", source
    )
    assert hardcoded is None, (
        f"Found hardcoded version literal in {source_path}: "
        f"{hardcoded.group(0) if hardcoded else ''}. "
        "Use importlib.metadata.version('polily') instead."
    )


def test_no_hardcoded_version_literal_in_pyproject():
    """pyproject.toml's [project] table MUST declare `dynamic = [\"version\"]`
    and MUST NOT contain a literal `version = \"X.Y.Z\"` line.

    This is the second leg of the fix — v0.9.1/v0.9.2 drift happened
    because BOTH pyproject.toml and __init__.py had literals, and we forgot
    to bump both. The source-scan in _init_py above catches half; this one
    catches the other half.
    """
    import tomllib  # stdlib in Python 3.11+ (Polily's minimum)

    pyproject_path = Path(__file__).parent.parent / "pyproject.toml"
    with pyproject_path.open("rb") as f:
        data = tomllib.load(f)

    project_table = data.get("project", {})
    dynamic = project_table.get("dynamic", [])
    assert "version" in dynamic, (
        f"pyproject.toml [project] must declare `dynamic = [\"version\"]`; "
        f"got dynamic={dynamic!r}"
    )
    assert "version" not in project_table, (
        f"pyproject.toml [project] has a literal `version = ...` line. "
        f"Remove it — version is resolved from the git tag via hatch-vcs. "
        f"Got: version={project_table['version']!r}"
    )
