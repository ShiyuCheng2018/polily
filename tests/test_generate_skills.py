"""Generator script — produces manual.md (polily) and SKILL.md (plugin) deterministically."""
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GENERATOR = REPO_ROOT / "scripts" / "generate_skills.py"


def test_generator_writes_manual_md(tmp_path):
    """Run generator with --plugin-repo to a temp dir; verify manual.md is written in polily."""
    fake_plugin = tmp_path / "fake-polily-plugin"
    (fake_plugin / "skills" / "polily").mkdir(parents=True)
    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--plugin-repo", str(fake_plugin)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Generator failed: {result.stderr}"
    manual = REPO_ROOT / "polily" / "agents" / "manual.md"
    assert manual.exists()
    content = manual.read_text()
    assert "GENERATED FILE — DO NOT EDIT" in content
    assert "## 1. Who You Are" in content
    assert "## 7. Per-Call Inputs" in content


def test_generator_writes_skill_md(tmp_path):
    fake_plugin = tmp_path / "fake-polily-plugin"
    (fake_plugin / "skills" / "polily").mkdir(parents=True)
    subprocess.run(
        [sys.executable, str(GENERATOR), "--plugin-repo", str(fake_plugin)],
        cwd=REPO_ROOT,
        check=True,
    )
    skill = fake_plugin / "skills" / "polily" / "SKILL.md"
    assert skill.exists()
    content = skill.read_text()
    assert content.startswith("---\nname: polily\n")
    assert "GENERATED FILE — DO NOT EDIT" in content
    assert "## 1. Who You Are" in content


def test_generator_check_mode_returns_zero_when_in_sync(tmp_path):
    """--check exits 0 when manual.md matches generation."""
    fake_plugin = tmp_path / "fake-polily-plugin"
    (fake_plugin / "skills" / "polily").mkdir(parents=True)
    # First, generate fresh
    subprocess.run(
        [sys.executable, str(GENERATOR), "--plugin-repo", str(fake_plugin)],
        cwd=REPO_ROOT,
        check=True,
    )
    # Then --check should pass
    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--plugin-repo", str(fake_plugin), "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0


def test_generator_check_mode_returns_nonzero_when_drift(tmp_path):
    """--check exits non-zero when manual.md drifted (e.g., hand-edited)."""
    fake_plugin = tmp_path / "fake-polily-plugin"
    (fake_plugin / "skills" / "polily").mkdir(parents=True)
    subprocess.run(
        [sys.executable, str(GENERATOR), "--plugin-repo", str(fake_plugin)],
        cwd=REPO_ROOT,
        check=True,
    )
    # Hand-modify manual.md to simulate drift
    manual = REPO_ROOT / "polily" / "agents" / "manual.md"
    original = manual.read_text()
    manual.write_text(original + "\n\nHAND-EDIT DRIFT\n")
    try:
        result = subprocess.run(
            [sys.executable, str(GENERATOR), "--plugin-repo", str(fake_plugin), "--check"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
    finally:
        # Restore the canonical content (regenerate)
        subprocess.run(
            [sys.executable, str(GENERATOR), "--plugin-repo", str(fake_plugin)],
            cwd=REPO_ROOT,
            check=True,
        )
