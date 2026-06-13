"""Skills — reusable know-how the chara can read AND write (hermes-style).

A skill is a directory holding a SKILL.md with YAML frontmatter (the Anthropic
agent-skills format hermes uses):

    ---
    name: bake-a-page
    description: One line shown in the skill index.
    ---
    The full know-how, read on demand.

Search order (first hit wins on name collisions — the chara's own learning
shadows everything, hermes resolves ~/.hermes/skills first the same way):

    1. <sandbox>/workspace/skills/   the chara's OWN skills — it writes these
                                     itself (create_skill): self-improvement
    2. ~/.lunamoth/skills/           the user's global library
    3. <repo>/skills/                bundled examples

Progressive disclosure: the system prompt carries only the index (name +
description, one line each); the full text is fetched with read_skill when
actually needed — long skills never tax every turn.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from ..config import ROOT, SANDBOX_ROOT

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_FRONT_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.S)

MAX_SKILL_CHARS = 24_000


def parse_frontmatter(raw: str) -> tuple[dict[str, str], str]:
    """Tiny YAML-lite frontmatter parser (key: value lines only — like hermes,
    we deliberately avoid a YAML dependency for two fields)."""
    m = _FRONT_RE.match(raw)
    if not m:
        return {}, raw
    meta: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            meta[k.strip().lower()] = v.strip().strip("\"'")
    return meta, raw[m.end():]


class SkillStore:
    def __init__(self, own_dir: Path | None = None, dirs: "list[Path] | None" = None):
        self.own_dir = own_dir or (SANDBOX_ROOT / "workspace" / "skills")
        home = Path(os.getenv("LUNAMOTH_HOME", Path.home() / ".lunamoth")).expanduser()
        self.dirs: list[tuple[str, Path]] = [("own", self.own_dir)] + [
            ("user", home / "skills"),
            ("bundled", ROOT / "skills"),
        ] if dirs is None else [("own", self.own_dir)] + [("user", d) for d in dirs]

    # ---- discovery ------------------------------------------------------------------

    def scan(self) -> list[dict[str, Any]]:
        """All skills, first-hit-wins by name across the search order."""
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for origin, base in self.dirs:
            if not base.is_dir():
                continue
            for skill_file in sorted(base.glob("*/SKILL.md")):
                try:
                    meta, _ = parse_frontmatter(skill_file.read_text(encoding="utf-8"))
                except OSError:
                    continue
                name = (meta.get("name") or skill_file.parent.name).strip()
                if not name or name in seen:
                    continue
                seen.add(name)
                out.append({
                    "name": name,
                    "description": meta.get("description", "").strip(),
                    "origin": origin,
                    "path": str(skill_file),
                })
        return out

    def read(self, name: str) -> str:
        """Full SKILL.md text for one skill (frontmatter included)."""
        for skill in self.scan():
            if skill["name"] == name:
                try:
                    raw = Path(skill["path"]).read_text(encoding="utf-8")
                except OSError as e:
                    raise ValueError(f"skill {name!r} unreadable: {e}") from e
                # Don't slice silently (audit #26): if the file is over the cap,
                # return the head WITH an explicit, in-band notice so the chara
                # knows the tail is missing rather than acting on a quiet cut.
                if len(raw) > MAX_SKILL_CHARS:
                    return (
                        raw[:MAX_SKILL_CHARS]
                        + f"\n\n[notice: skill {name!r} is {len(raw)} chars; only the first "
                        f"{MAX_SKILL_CHARS} are shown. The rest was NOT loaded — open the file "
                        f"directly ({skill['path']}) if you need it.]"
                    )
                return raw
        raise ValueError(f"no skill named {name!r} — see the skill index in your context")

    # ---- self-improvement -----------------------------------------------------------

    def create(self, name: str, description: str, content: str) -> Path:
        """Write (or overwrite) one of the chara's OWN skills.

        Only the chara's own directory is writable here — user/bundled skills
        are someone else's work. Overwriting an own skill is how it revises
        its know-how (hermes's local-skills-first rule makes the revision win).
        """
        name = (name or "").strip().lower()
        if not _NAME_RE.match(name):
            raise ValueError("skill name must be kebab-case: letters/digits/hyphens, e.g. tend-the-garden")
        description = " ".join((description or "").split())
        if not description:
            raise ValueError("a one-line description is required (it is the index entry)")
        body = (content or "").strip()
        if not body:
            raise ValueError("content is empty")
        meta, stripped = parse_frontmatter(body)
        if meta:
            body = stripped.strip()  # engine owns the frontmatter; keep one source of truth
        text = f"---\nname: {name}\ndescription: {description}\n---\n\n{body}\n"
        # Reject an over-cap skill instead of silently truncating it (audit #26):
        # a half-written SKILL.md is worse than a refused one, and a quiet cut
        # violates the explicitness rule. Tell the chara to split or trim.
        if len(text) > MAX_SKILL_CHARS:
            raise ValueError(
                f"skill {name!r} is {len(text)} chars but a SKILL.md is capped at "
                f"{MAX_SKILL_CHARS}. Nothing was saved — silently cutting it would leave a "
                f"truncated skill. Trim it, or split the know-how across two named skills."
            )
        path = self.own_dir / name / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    # ---- prompt block ---------------------------------------------------------------

    def render_block(self) -> str:
        """The skill index for the system prompt ('' when there are none)."""
        skills = self.scan()
        if not skills:
            return ""
        lines = ["Skills available to you (read_skill(name) fetches the full text when you need it):"]
        for s in skills:
            tag = " (yours)" if s["origin"] == "own" else ""
            lines.append(f"  {s['name']}{tag} — {s['description']}")
        lines.append(
            "You can write new skills for yourself with create_skill — distill anything "
            "you had to figure out the hard way, so the next time is easy."
        )
        return "\n".join(lines)
