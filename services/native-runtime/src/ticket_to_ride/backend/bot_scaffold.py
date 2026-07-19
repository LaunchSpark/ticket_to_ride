from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


class BotScaffoldError(ValueError):
    """Raised when a new bot cannot be scaffolded from the template."""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[5]


def _default_bots_dir() -> Path:
    return _repo_root() / "integrations" / "external" / "bots"


def _default_template_path() -> Path:
    return _repo_root() / "integrations" / "external" / "templates" / "bots" / "build_your_bot_here.py"


def slugify_bot_name(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    if not slug:
        raise BotScaffoldError("Bot name must contain at least one letter or number.")
    if slug[0].isdigit():
        slug = f"bot_{slug}"
    return slug


def class_name_from_slug(slug: str) -> str:
    return "".join(part.capitalize() for part in slug.split("_") if part)


@dataclass(frozen=True)
class ScaffoldedBot:
    bot_id: str
    name: str
    path: str


def scaffold_bot(
    name: str,
    *,
    bots_dir: Path | None = None,
    template_path: Path | None = None,
    existing_bot_ids: set[str] | frozenset[str] | None = None,
) -> ScaffoldedBot:
    display_name = name.strip()
    if not display_name:
        raise BotScaffoldError("Bot name is required.")
    if '"' in display_name or "\\" in display_name:
        raise BotScaffoldError("Bot name must not contain quotes or backslashes.")

    slug = slugify_bot_name(display_name)
    if existing_bot_ids and slug.casefold() in {bot_id.casefold() for bot_id in existing_bot_ids}:
        raise BotScaffoldError(f"A bot with id '{slug}' already exists.")

    resolved_bots_dir = bots_dir or _default_bots_dir()
    target_path = resolved_bots_dir / f"{slug}.py"

    source = (template_path or _default_template_path()).read_text(encoding="utf-8")
    source = source.replace('"id": "your_bot_id"', f'"id": "{slug}"')
    source = source.replace('"name": "Your Bot Name"', f'"name": "{display_name}"')
    source = source.replace("YourBotName", class_name_from_slug(slug))
    try:
        with target_path.open("x", encoding="utf-8") as handle:
            handle.write(source)
    except FileExistsError as exc:
        raise BotScaffoldError(f"A bot module named '{slug}' already exists.") from exc
    return ScaffoldedBot(bot_id=slug, name=display_name, path=str(target_path))
