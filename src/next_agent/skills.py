"""Skill system — self-improving agent skills.

Skills are .md files with YAML frontmatter stored in:
- ~/.nextagent/skills/  (user/agent-created skills)
- next_agent/skills/    (bundled skills)

Inspired by Hermes agent skills. Skills are loaded at session start and
injected into the system prompt. They never change mid-session to preserve
the DeepSeek prefix cache.

Format:
---
name: python-import-check
description: Before editing Python files, verify imports resolve
trigger: editing .py files in any project
created_by: agent
created_at: 2026-06-14
use_count: 5
---

## Pattern
...
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ── Skill data model ──────────────────────────────────────────

@dataclass
class Skill:
    """A single skill loaded from a markdown file."""
    name: str
    description: str
    trigger: str
    created_by: str = "agent"
    created_at: str = ""
    use_count: int = 0
    body: str = ""
    source_path: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "trigger": self.trigger,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "use_count": self.use_count,
            "source": self.source_path,
        }

    def to_prompt_extension(self) -> str:
        """Render this skill as a prompt extension block."""
        return f"""## Skill: {self.name}
**Trigger**: {self.trigger}
{self.body}
"""


# ── Frontmatter parser ────────────────────────────────────────

def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from markdown.

    Returns (frontmatter_dict, body_text).
    """
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not match:
        return {}, text

    frontmatter_text = match.group(1)
    body = text[match.end():]

    fm = {}
    for line in frontmatter_text.splitlines():
        line = line.strip()
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            if key == "use_count":
                try:
                    fm[key] = int(value)
                except ValueError:
                    fm[key] = 0
            else:
                fm[key] = value

    return fm, body


# ── SkillManager ──────────────────────────────────────────────

# Triggers for auto-skill creation
TRIGGERS = [
    "same_error_3x",        # Same error type appears 3+ times
    "user_correction",      # User corrected the agent's behavior
    "successful_pattern",   # A complex workflow succeeded
    "new_workflow",         # Agent discovered a new effective approach
]

SKILL_PROMPT_TEMPLATE = """## Loaded Skills

The following skills are active for this session. Use them to guide your behavior.

{skills}

---
*Skills are automatically loaded based on the current context. Use /skills to see all available skills.*"""


class SkillManager:
    """Manages agent skills loaded from markdown files.

    Skills are scanned once at session start. The result is injected into
    the system prompt and never changes mid-session (preserves prefix cache).
    """

    def __init__(self):
        self._skills: dict[str, Skill] = {}
        self._scanned = False
        self._skill_dirs: list[Path] = []

    @property
    def skills(self) -> dict[str, Skill]:
        """Get all loaded skills (lazy scan on first access)."""
        if not self._scanned:
            self.scan()
        return self._skills

    # ── Discovery ───────────────────────────────────────────

    def _resolve_skill_dirs(self) -> list[Path]:
        """Find all skill directories in search order."""
        dirs = []

        # 1. Bundled skills (next_agent/skills/ relative to CWD or package)
        bundled = Path.cwd() / "next_agent" / "skills"
        if bundled.exists():
            dirs.append(bundled)

        # 2. User skills (~/.nextagent/skills/)
        user_dir = Path.home() / ".nextagent" / "skills"
        if user_dir.exists():
            dirs.append(user_dir)

        return dirs

    def scan(self) -> list[Skill]:
        """Scan all skill directories and load skills.

        Returns list of loaded Skill objects. Safe to call multiple times;
        subsequent calls are no-ops once scanned.
        """
        if self._scanned:
            return list(self._skills.values())

        self._skill_dirs = self._resolve_skill_dirs()
        self._skills.clear()

        for dir_path in self._skill_dirs:
            if not dir_path.exists():
                continue
            for fp in sorted(dir_path.glob("*.md")):
                try:
                    skill = self._load_skill_file(fp)
                    if skill and skill.name not in self._skills:
                        self._skills[skill.name] = skill
                except Exception:
                    continue

        self._scanned = True
        return list(self._skills.values())

    def _load_skill_file(self, filepath: Path) -> Skill | None:
        """Load a single skill from a markdown file."""
        try:
            text = filepath.read_text(encoding="utf-8")
        except Exception:
            return None

        fm, body = _parse_frontmatter(text)

        name = fm.get("name", filepath.stem)
        if not name:
            return None

        return Skill(
            name=name,
            description=fm.get("description", ""),
            trigger=fm.get("trigger", ""),
            created_by=fm.get("created_by", "unknown"),
            created_at=fm.get("created_at", ""),
            use_count=fm.get("use_count", 0),
            body=body.strip(),
            source_path=str(filepath),
        )

    # ── Relevance matching ──────────────────────────────────

    def relevant_for(
        self,
        user_input: str = "",
        project: str = "",
    ) -> list[Skill]:
        """Return skills relevant to the given user input and project context.

        Matching strategy:
        1. Check trigger keywords against user_input (case-insensitive)
        2. Check project name in trigger/description
        3. Check file extensions mentioned in trigger vs project context

        Args:
            user_input: The user's current request.
            project: Project name or description.

        Returns:
            List of matching Skill objects, sorted by use_count descendant.
        """
        if not self._scanned:
            self.scan()

        input_lower = user_input.lower() if user_input else ""
        project_lower = project.lower() if project else ""

        matched = []
        for skill in self._skills.values():
            trigger_lower = skill.trigger.lower()
            desc_lower = skill.description.lower()

            score = 0

            # Token-level matching against user input
            if input_lower:
                input_tokens = set(input_lower.split())
                trigger_tokens = set(trigger_lower.split())
                overlap = input_tokens & trigger_tokens
                score += len(overlap) * 3

                desc_tokens = set(desc_lower.split())
                desc_overlap = input_tokens & desc_tokens
                score += len(desc_overlap)

            # Project match
            if project_lower:
                if project_lower in trigger_lower or project_lower in desc_lower:
                    score += 5

            # File extension patterns (e.g., ".py" in trigger)
            if input_lower:
                ext_matches = re.findall(r'\.\w+', trigger_lower)
                for ext in ext_matches:
                    if ext in input_lower:
                        score += 2

            if score > 0:
                matched.append((score, skill))

        # Sort by score, then use_count
        matched.sort(key=lambda x: (x[0], x[1].use_count), reverse=True)

        return [skill for _, skill in matched]

    def get_prompt_extension(
        self,
        user_input: str = "",
        project: str = "",
    ) -> str:
        """Build a prompt extension string with relevant skills.

        Called ONCE at session start. The result is frozen into the prefix.
        """
        relevant = self.relevant_for(user_input, project)

        if not relevant:
            return ""

        skill_blocks = []
        for skill in relevant[:5]:  # Top 5 most relevant
            skill_blocks.append(skill.to_prompt_extension())

        return SKILL_PROMPT_TEMPLATE.format(
            skills="\n".join(skill_blocks)
        )

    # ── Management ──────────────────────────────────────────

    def get(self, name: str) -> Skill | None:
        """Get a skill by name."""
        if not self._scanned:
            self.scan()
        return self._skills.get(name)

    def list_skills(self) -> list[dict]:
        """List all available skills with metadata."""
        if not self._scanned:
            self.scan()
        return [s.to_dict() for s in sorted(
            self._skills.values(),
            key=lambda s: s.use_count,
            reverse=True,
        )]

    def stats(self) -> dict:
        """Get skill statistics."""
        if not self._scanned:
            self.scan()
        skills = list(self._skills.values())
        return {
            "total": len(skills),
            "by_creator": {
                "agent": sum(1 for s in skills if s.created_by == "agent"),
                "user": sum(1 for s in skills if s.created_by == "user"),
            },
            "total_uses": sum(s.use_count for s in skills),
            "top_skills": [s.name for s in sorted(
                skills, key=lambda s: s.use_count, reverse=True
            )[:5]],
        }

    def create_skill(
        self,
        name: str,
        description: str,
        body: str,
        trigger: str = "",
        created_by: str = "agent",
    ) -> Skill:
        """Create a new skill and save it to the user skills directory.

        The skill is written to ~/.nextagent/skills/<name>.md
        """
        user_dir = Path.home() / ".nextagent" / "skills"
        user_dir.mkdir(parents=True, exist_ok=True)

        created_at = time.strftime("%Y-%m-%d")
        skill = Skill(
            name=name,
            description=description,
            trigger=trigger,
            created_by=created_by,
            created_at=created_at,
            use_count=0,
            body=body,
            source_path=str(user_dir / f"{name}.md"),
        )

        # Build markdown
        fm_lines = [
            "---",
            f"name: {name}",
            f"description: {description}",
            f"trigger: {trigger}",
            f"created_by: {created_by}",
            f"created_at: {created_at}",
            "use_count: 0",
            "---",
        ]
        md_content = "\n".join(fm_lines) + "\n\n" + body

        filepath = user_dir / f"{name}.md"
        filepath.write_text(md_content, encoding="utf-8")

        # Add to in-memory store
        self._skills[name] = skill

        return skill

    def reload(self) -> None:
        """Force re-scan of all skill directories."""
        self._scanned = False
        self.scan()
