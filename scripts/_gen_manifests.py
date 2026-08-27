"""Generate manifest.yaml for every skill (P1-7). Idempotent, safe to re-run."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
TESTS = ROOT / "tests" / "skills"

# Map of skill dir-name -> (provides capability, requires list)
# Only skills with a corresponding test get a test_command.
CAPABILITIES = {
    "agent-browser": ("browser-automation", ["playwright"]),
    "aipm-news-digest": ("news-digest", []),
    "brave-search": ("web-search", ["BRAVE_API_KEY"]),
    "codebase-design": ("architecture-design", []),
    "code-review": ("code-review", []),
    "component-library-selector": ("component-selection", []),
    "design-spec-skill-creator": ("design-spec-authoring", []),
    "diagnosing-bugs": ("bug-diagnosis", []),
    "domain-modeling": ("domain-modeling", []),
    "douyin-reader": ("douyin-content-reading", []),
    "figma-reader": ("figma-api", ["FIGMA_TOKEN"]),
    "find-skills": ("skill-discovery", []),
    "frontend-design": ("frontend-design", []),
    "github": ("github-integration", ["GITHUB_TOKEN"]),
    "grounded-citations": ("citation-grounding", []),
    "improve-codebase-architecture": ("architecture-improvement", []),
    "liquid-glass-builder": ("liquid-glass-ui", []),
    "loop-engineering": ("loop-engineering", []),
    "notion": ("notion-integration", ["NOTION_API_KEY"]),
    "obsidian": ("obsidian-integration", []),
    "product-manager": ("product-management", []),
    "prototype": ("prototyping", []),
    "prototype-validator": ("prototype-validation", []),
    "research": ("research", []),
    "resolving-merge-conflicts": ("merge-conflict-resolution", []),
    "self-improving-agent": ("self-improvement", []),
    "skill-creator": ("skill-authoring", []),
    "skill-manager": ("skill-management", []),
    "stock-analysis": ("stock-analysis", []),
    "storybook-chromatic": ("storybook-integration", []),
    "style-dictionary-sync": ("design-token-sync", []),
    "summarize": ("summarization", []),
    "tavily-search": ("web-search", ["TAVILY_API_KEY"]),
    "to-spec": ("spec-generation", []),
    "to-tickets": ("ticket-generation", []),
    "trello": ("trello-integration", ["TRELLO_API_KEY", "TRELLO_API_TOKEN"]),
    "triage": ("issue-triage", []),
    "ui-design-system": ("design-system", []),
    "ui-review-checklist": ("ui-review", []),
    "wayfinder": ("navigation", []),
    "weather": ("weather-query", []),
    "wechat-reader": ("wechat-content-reading", []),
    "youtube-watcher": ("youtube-content-reading", []),
}


def _manifest_text(skill: str, has_test: bool) -> str:
    provides, requires = CAPABILITIES.get(skill, (skill, []))
    lines = ["version: \"1.0\"", "provides:"]
    lines.append(f"  - {provides}")
    if requires:
        lines.append("requires:")
        for r in requires:
            lines.append(f"  - {r}")
    if has_test:
        test_dir = skill.replace("-", "_")
        lines.append(f'test_command: "python -m pytest tests/skills/{test_dir}"')
    return "\n".join(lines) + "\n"


def main() -> int:
    created = 0
    tested = 0
    for skill_dir in sorted(SKILLS.iterdir()):
        if not skill_dir.is_dir():
            continue
        name = skill_dir.name
        test_dir = name.replace("-", "_")
        has_test = (TESTS / test_dir / f"test_{test_dir}.py").exists()
        manifest = skill_dir / "manifest.yaml"
        manifest.write_text(_manifest_text(name, has_test), encoding="utf-8")
        created += 1
        if has_test:
            tested += 1
    print(f"Generated {created} manifest.yaml ({tested} tested, {created - tested} untested)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
