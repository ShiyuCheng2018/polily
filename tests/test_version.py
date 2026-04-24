"""Version resolution tests.

After v0.9.3, `polily.__version__` is derived from package metadata
(installed distribution's `version` field), which in turn comes from
the git tag via `hatch-vcs`. There is no hardcoded version string
anywhere in the source tree — this is enforced by `test_no_hardcoded_version_literal_in_init`
and `test_no_hardcoded_version_literal_in_pyproject`.

The HTTP `User-Agent` header sent to Polymarket APIs is part of the same
invariant: `polily/core/config.py` and `config.example.yaml` must not
hardcode a version literal into `user_agent`. Enforced by
`test_no_hardcoded_version_literal_in_config_py`,
`test_api_config_user_agent_uses_dynamic_version`, and
`test_no_hardcoded_version_literal_in_config_example_yaml`.
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


def test_no_hardcoded_version_literal_in_config_py():
    """Source of polily/core/config.py must not contain a literal version
    string in the ``user_agent`` default.

    Drift-trap: v0.9.0–v0.9.2 shipped with ``user_agent = "polymarket-polily/0.1"``
    and ``user_agent = "polily/0.9"``, which never got updated when the package
    version bumped. The fix is to derive the default from ``polily.__version__``
    at runtime via a ``default_factory``. This test fails if anyone reintroduces
    a hardcoded version literal.
    """
    from polily.core import config as config_module

    source_path = Path(inspect.getfile(config_module))
    source = source_path.read_text()
    # Match `user_agent ... "...0.9..."` style hardcoded versioned literals
    # (digits with at least one dot). Tolerates Pydantic's `user_agent: str = "..."`
    # form between the field name and the quote. Does not match
    # `f"polily/{__version__}"` or `"polily/"` (no version digit).
    hardcoded = re.search(
        r"""user_agent[^'"\n]*?['"][^'"]*\d+\.\d+""", source
    )
    assert hardcoded is None, (
        f"Found hardcoded version literal in user_agent default in {source_path}: "
        f"{hardcoded.group(0) if hardcoded else ''}. "
        "Use a default_factory that reads polily.__version__ instead."
    )


def test_api_config_user_agent_uses_dynamic_version():
    """``ApiConfig().user_agent`` must be derived from ``polily.__version__``
    at runtime.

    The HTTP header sent to Polymarket APIs should always reflect the actually
    installed package version, not a stale literal. If this test fails because
    __version__ changed shape, update the assertion — but never pin a literal.
    """
    from polily.core.config import ApiConfig

    ua = ApiConfig().user_agent
    assert ua.startswith("polily/"), (
        f"user_agent {ua!r} must start with 'polily/'"
    )
    assert polily.__version__ in ua, (
        f"user_agent {ua!r} must contain polily.__version__="
        f"{polily.__version__!r}"
    )


def test_no_hardcoded_version_literal_in_config_example_yaml():
    """``config.example.yaml`` must not pin a version into ``user_agent``.

    Either the key is absent (so the dynamic ``default_factory`` in ApiConfig
    kicks in) or it is an empty / non-versioned string with an explanatory
    comment. This prevents the example config from re-drifting the same way
    the Pydantic default did in v0.9.0–v0.9.2.
    """
    yaml_path = Path(__file__).parent.parent / "config.example.yaml"
    text = yaml_path.read_text()
    hardcoded = re.search(
        r"""^\s*user_agent\s*:\s*["'][^"']*\d+\.\d+""",
        text,
        flags=re.MULTILINE,
    )
    assert hardcoded is None, (
        f"Found hardcoded versioned user_agent in config.example.yaml: "
        f"{hardcoded.group(0) if hardcoded else ''!r}. "
        "Remove the version literal — the ApiConfig default_factory handles it."
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
