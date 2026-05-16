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
    # v0.12.0 audience split: SKILL.md's §1 is "About Polily" (external
    # framing), NOT "Who You Are" (internal agent persona). See
    # test_skill_md_excludes_internal_only_blocks.
    assert "## 1. About Polily" in content


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


def test_skill_md_excludes_internal_only_blocks(tmp_path):
    """v0.12.0 audience split: SKILL.md (external) must drop content
    wrapped in `<!-- internal-only -->...<!-- /internal-only -->` tags.

    The internal-only sections target polily's runtime agent (system
    prompt) — persona injection, per-call YAML protocol, strategy
    fallback flow. An external Claude Code session loading the skill
    is NOT polily's agent and gets confused / misled by these.
    """
    fake_plugin = tmp_path / "fake-polily-plugin"
    (fake_plugin / "skills" / "polily").mkdir(parents=True)
    subprocess.run(
        [sys.executable, str(GENERATOR), "--plugin-repo", str(fake_plugin)],
        cwd=REPO_ROOT,
        check=True,
    )
    skill = (fake_plugin / "skills" / "polily" / "SKILL.md").read_text()

    # Persona injection (§1) → external session is NOT the agent
    assert "You are the analytical agent of Polily" not in skill, (
        "SKILL.md must not contain the agent-persona sentence — "
        "external sessions are not polily's runtime agent"
    )
    # Per-call YAML protocol (§7) → external session has no such injection
    assert "## 7. Per-Call Inputs" not in skill, (
        "SKILL.md must drop §7 — no per-call YAML in external sessions"
    )
    # Strategy fallback flow (§8) → runtime mechanism, irrelevant externally
    assert "## 8. Active Strategy" not in skill, (
        "SKILL.md must drop §8 — strategy fallback is agent runtime only"
    )


def test_skill_md_contains_external_only_blocks(tmp_path):
    """SKILL.md must contain external-only content that's absent from manual.md."""
    fake_plugin = tmp_path / "fake-polily-plugin"
    (fake_plugin / "skills" / "polily").mkdir(parents=True)
    subprocess.run(
        [sys.executable, str(GENERATOR), "--plugin-repo", str(fake_plugin)],
        cwd=REPO_ROOT,
        check=True,
    )
    skill = (fake_plugin / "skills" / "polily" / "SKILL.md").read_text()
    manual = (REPO_ROOT / "polily" / "agents" / "manual.md").read_text()

    # External-only §1 framing ("About Polily" — descriptive, not persona)
    assert "## 1. About Polily" in skill, (
        "SKILL.md must have external-only §1 'About Polily' framing"
    )
    assert "## 1. About Polily" not in manual, (
        "manual.md must NOT have external-only §1 (its §1 is the internal persona)"
    )

    # External-only §10 codebase pointers (entry points + CLAUDE.md).
    # Renumbered from §9 → §10 in v0.12.0 hotfix bundle when §9 was reassigned
    # to "Polily's Analytical Methodology (runtime lookup)" — the more
    # frequently-used chat-mode entry point.
    assert "## 10. Codebase Pointers" in skill, (
        "SKILL.md must have §10 codebase pointers for external developers"
    )
    assert "## 10. Codebase Pointers" not in manual, (
        "manual.md doesn't need codebase pointers — agent has its own navigation"
    )


def test_manual_md_keeps_internal_only_blocks(tmp_path):
    """manual.md (internal) keeps the agent-runtime sections that SKILL.md drops."""
    fake_plugin = tmp_path / "fake-polily-plugin"
    (fake_plugin / "skills" / "polily").mkdir(parents=True)
    subprocess.run(
        [sys.executable, str(GENERATOR), "--plugin-repo", str(fake_plugin)],
        cwd=REPO_ROOT,
        check=True,
    )
    manual = (REPO_ROOT / "polily" / "agents" / "manual.md").read_text()

    # manual.md still has the original persona, per-call YAML, and fallback flow
    assert "You are the analytical agent of Polily" in manual
    assert "## 7. Per-Call Inputs" in manual
    assert "## 8. Active Strategy" in manual


def test_skill_md_drops_maintainer_log_leak(tmp_path):
    """§5 mentions agent_feedback.log; the parenthetical "polily maintainers
    grep this..." is internal-only tooling leak that should NOT appear in
    the external SKILL.md.

    The fact that the log exists (it's a file in data_dir/logs/) is fine
    to mention for both audiences; the maintainer-harvesting context is
    internal-only.
    """
    fake_plugin = tmp_path / "fake-polily-plugin"
    (fake_plugin / "skills" / "polily").mkdir(parents=True)
    subprocess.run(
        [sys.executable, str(GENERATOR), "--plugin-repo", str(fake_plugin)],
        cwd=REPO_ROOT,
        check=True,
    )
    skill = (fake_plugin / "skills" / "polily" / "SKILL.md").read_text()
    assert "Polily maintainers grep" not in skill, (
        "SKILL.md leaked internal tooling reference (maintainer log harvesting)"
    )


def test_skill_md_includes_strategy_lookup_section(tmp_path):
    """SKILL.md must include §9 strategy lookup procedure — the
    chat-mode entry point for polily's analytical methodology. Without
    this, Claude has the manual but no methodology, leading to generic-
    finance answers that diverge from polily's TUI analyses.

    Pattern is "runtime lookup, not bundled content":
      1. Check active_strategy in user's polily.db
      2. If 'user', read user_strategy.text
      3. Else fetch default.md from polily's GitHub master
    """
    fake_plugin = tmp_path / "fake-polily-plugin"
    (fake_plugin / "skills" / "polily").mkdir(parents=True)
    subprocess.run(
        [sys.executable, str(GENERATOR), "--plugin-repo", str(fake_plugin)],
        cwd=REPO_ROOT,
        check=True,
    )
    skill = (fake_plugin / "skills" / "polily" / "SKILL.md").read_text()

    # Section heading
    assert "## 9." in skill and "Methodology" in skill, (
        "SKILL.md must have §9 methodology lookup section"
    )

    # The three lookup keys the procedure relies on
    assert "active_strategy" in skill, "Must reference active_strategy config key"
    assert "user_strategy" in skill, "Must reference user_strategy table"

    # GitHub URL for the official methodology — drives repo visibility and
    # keeps SKILL.md from going stale when default.md changes.
    assert "raw.githubusercontent.com/ShiyuCheng2018/polily" in skill, (
        "SKILL.md must include the canonical GitHub raw URL for default.md "
        "fetching — keeps methodology fresh without regen"
    )


def test_manual_md_does_not_include_strategy_lookup(tmp_path):
    """manual.md (internal agent prompt) must NOT contain the runtime
    lookup procedure — polily's internal agent already gets the active
    strategy injected by _build_prompt as part of its prompt stack.
    Telling the agent to also `curl` from GitHub would be redundant
    and bypass the user's active_strategy choice.
    """
    fake_plugin = tmp_path / "fake-polily-plugin"
    (fake_plugin / "skills" / "polily").mkdir(parents=True)
    subprocess.run(
        [sys.executable, str(GENERATOR), "--plugin-repo", str(fake_plugin)],
        cwd=REPO_ROOT,
        check=True,
    )
    manual = (REPO_ROOT / "polily" / "agents" / "manual.md").read_text()
    assert "raw.githubusercontent.com" not in manual, (
        "manual.md must not include GitHub-fetch URL — internal agent "
        "receives strategy via _build_prompt injection"
    )
    assert "## 9." not in manual, (
        "manual.md must not have §9 strategy lookup — it's external-only"
    )


def test_no_audience_wrapper_tags_leak_into_outputs(tmp_path):
    """Both outputs must have the audience-wrapper tags stripped from the
    rendered content. Leftover `<!-- internal-only -->` markers waste
    context tokens on every load and look like noise to readers.
    """
    fake_plugin = tmp_path / "fake-polily-plugin"
    (fake_plugin / "skills" / "polily").mkdir(parents=True)
    subprocess.run(
        [sys.executable, str(GENERATOR), "--plugin-repo", str(fake_plugin)],
        cwd=REPO_ROOT,
        check=True,
    )
    manual = (REPO_ROOT / "polily" / "agents" / "manual.md").read_text()
    skill = (fake_plugin / "skills" / "polily" / "SKILL.md").read_text()

    for path, text in [("manual.md", manual), ("SKILL.md", skill)]:
        assert "internal-only" not in text, (
            f"{path} contains a leftover internal-only wrapper tag — "
            "_filter_audience must strip same-audience markers too"
        )
        assert "external-only" not in text, (
            f"{path} contains a leftover external-only wrapper tag — "
            "_filter_audience must strip same-audience markers too"
        )


def test_skill_md_strategy_lookup_has_robust_fallback_ladder(tmp_path):
    """v0.12.0 hotfix (Whis re-review): §9 must use a multi-source fallback
    ladder, not a single curl-from-master that 404s when default.md isn't
    on master yet (pre-release window).

    Required sources in order:
      1. user_strategy.text (local DB, if polily installed + customized)
      2. Local default.md via polily.__file__ (if polily installed)
      3. GitHub fetch with curl --fail (last resort; never confabulate
         on 404)
    """
    fake_plugin = tmp_path / "fake-polily-plugin"
    (fake_plugin / "skills" / "polily").mkdir(parents=True)
    subprocess.run(
        [sys.executable, str(GENERATOR), "--plugin-repo", str(fake_plugin)],
        cwd=REPO_ROOT,
        check=True,
    )
    skill = (fake_plugin / "skills" / "polily" / "SKILL.md").read_text()

    # All three sources must be documented
    assert "user_strategy" in skill, "Source 1 (user_strategy) missing"
    assert "polily.__file__" in skill, (
        "Source 2 (local default.md via polily.__file__) missing — "
        "robust fallback needed for pre-master-merge window"
    )
    assert "curl -sf" in skill or "curl --fail" in skill, (
        "Source 3 must use curl --fail (or -sf) so HTTP 404 doesn't get "
        "treated as methodology text"
    )

    # Graceful failure guidance — Claude must NOT confabulate when all
    # sources fail
    skill_lower = skill.lower()
    assert "do not confabulate" in skill_lower or "not confabulate" in skill_lower, (
        "§9 must explicitly tell Claude NOT to fabricate methodology when "
        "all fallback sources fail"
    )


def test_skill_md_strategy_lookup_mirrors_internal_fallback_criteria(tmp_path):
    """§9 Step 1 acceptance criteria for user_strategy.text must mirror
    the internal agent's §8 fallback triggers (empty / too short /
    missing structure / asks for execution / etc.) so chat-consultation
    methodology stays consistent with what the TUI dispatched."""
    fake_plugin = tmp_path / "fake-polily-plugin"
    (fake_plugin / "skills" / "polily").mkdir(parents=True)
    subprocess.run(
        [sys.executable, str(GENERATOR), "--plugin-repo", str(fake_plugin)],
        cwd=REPO_ROOT,
        check=True,
    )
    skill = (fake_plugin / "skills" / "polily" / "SKILL.md").read_text()

    # Concrete fallback criteria (vs loose "coherent" judgment)
    skill_lower = skill.lower()
    # At least 3 of these markers should appear
    structural_markers = [
        "non-empty",
        "whitespace",
        "lines",
        "markdown",
        "header",
        "destructive",
        "execute",
    ]
    found = sum(1 for m in structural_markers if m in skill_lower)
    assert found >= 4, (
        f"§9 Source 1 needs concrete fallback criteria (mirroring §8), "
        f"only found {found} of the expected structural markers"
    )


def test_skill_md_no_dangling_per_call_yaml_references(tmp_path):
    """Audit pass: external SKILL.md must not reference §7 / §8 /
    `official_strategy_path` / `per-call YAML` — those are all stripped
    in external output. Any remaining reference is a dangling pointer
    that confuses Claude.
    """
    fake_plugin = tmp_path / "fake-polily-plugin"
    (fake_plugin / "skills" / "polily").mkdir(parents=True)
    subprocess.run(
        [sys.executable, str(GENERATOR), "--plugin-repo", str(fake_plugin)],
        cwd=REPO_ROOT,
        check=True,
    )
    skill = (fake_plugin / "skills" / "polily" / "SKILL.md").read_text()

    # §9 strategy lookup itself talks about user_strategy etc. so we can't
    # blanket-ban; but specific dangling references must be gone.
    assert "official_strategy_path" not in skill, (
        "SKILL.md references official_strategy_path — defined in §7 which "
        "is internal-only. Dangling reference."
    )
    # `per §8` is the specific cross-reference pattern that was leaking
    assert "per §8" not in skill and "per §7" not in skill, (
        "SKILL.md has dangling 'per §7' / 'per §8' cross-reference — "
        "those sections are internal-only"
    )


def test_skill_md_yaml_description_covers_chat_consultation_trigger(tmp_path):
    """YAML description must mention chat-consultation triggers (follow-up
    questions about polily analyses), not just developer triggers.
    Without this, naive user queries like '为什么 edge 很薄' won't
    activate the skill.
    """
    fake_plugin = tmp_path / "fake-polily-plugin"
    (fake_plugin / "skills" / "polily").mkdir(parents=True)
    subprocess.run(
        [sys.executable, str(GENERATOR), "--plugin-repo", str(fake_plugin)],
        cwd=REPO_ROOT,
        check=True,
    )
    skill = (fake_plugin / "skills" / "polily" / "SKILL.md").read_text()
    frontmatter = skill.split("---", 2)[1]
    lower = frontmatter.lower()

    # Chat-consultation framing
    assert "follow-up" in lower or "analysis" in lower or "structure_score" in lower, (
        "YAML description must mention follow-up / analysis / structure_score "
        "to trigger on chat-consultation queries"
    )
    # Still has the negative trigger
    assert "do not activate" in lower or "not for" in lower or "exclude" in lower


def test_skill_md_yaml_description_has_negative_trigger(tmp_path):
    """SKILL.md's YAML frontmatter description must include a negative
    trigger — don't activate on generic Polymarket questions, only on
    polily-specific work. Prevents over-activation in unrelated sessions.
    """
    fake_plugin = tmp_path / "fake-polily-plugin"
    (fake_plugin / "skills" / "polily").mkdir(parents=True)
    subprocess.run(
        [sys.executable, str(GENERATOR), "--plugin-repo", str(fake_plugin)],
        cwd=REPO_ROOT,
        check=True,
    )
    skill = (fake_plugin / "skills" / "polily" / "SKILL.md").read_text()
    # Frontmatter spans first lines through closing `---`
    frontmatter = skill.split("---", 2)[1]
    lower = frontmatter.lower()
    assert "do not activate" in lower or "not for" in lower or "exclude" in lower, (
        "YAML description should explicitly tell Claude Code NOT to activate "
        "on generic Polymarket questions unrelated to the polily codebase"
    )


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
