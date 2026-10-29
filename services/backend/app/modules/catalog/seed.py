"""Load the catalog from `seeds/` into the database. Idempotent; run as the table owner.

    python -m app.modules.catalog.seed            # uses ALEMBIC/ADMIN/DATABASE_URL

Rules it enforces (D16, D30):
  * a persona's `prompt_version` is a content hash, so an edited prompt becomes a new row
    and every session that referenced the old text keeps pointing at it;
  * a rubric version is immutable: re-seeding the same version with different criteria
    fails loudly instead of silently changing what old scores meant;
  * scenarios are upserted by slug and re-pointed at their persona's newest prompt.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import asyncpg
from sqlalchemy.engine import make_url

SEEDS = Path(__file__).resolve().parents[3] / "seeds"
_FIELD = re.compile(r"^- \*\*(name|title|company|voice):\*\*\s*(.+)$", re.MULTILINE)
_INSTRUCTIONS = re.compile(r"## Instructions\s+```\s*\n(.*?)\n```", re.DOTALL)


@dataclass(frozen=True)
class PersonaSeed:
    slug: str
    name: str
    title: str
    company: str
    voice: str
    instructions: str

    @property
    def prompt_version(self) -> str:
        return hashlib.sha256(self.instructions.encode("utf-8")).hexdigest()[:12]


def parse_persona(path: Path) -> PersonaSeed:
    text = path.read_text(encoding="utf-8")
    fields = {k: v.strip() for k, v in _FIELD.findall(text)}
    match = _INSTRUCTIONS.search(text)
    missing = [k for k in ("name", "title", "company", "voice") if k not in fields]
    if missing or not match:
        raise ValueError(f"{path.name}: missing {missing or ['instructions block']}")
    # The voice line may carry a parenthetical note; the voice id is the first token.
    voice = fields["voice"].split()[0]
    return PersonaSeed(
        slug=path.stem,
        name=fields["name"],
        title=fields["title"],
        company=fields["company"],
        voice=voice,
        instructions=match.group(1).strip(),
    )


def load_seeds(root: Path = SEEDS) -> tuple[list[PersonaSeed], dict]:
    personas = [parse_persona(p) for p in sorted((root / "personas").glob("*.md"))]
    catalog = json.loads((root / "catalog.json").read_text(encoding="utf-8"))
    slugs = {p.slug for p in personas}
    criteria = {c["id"] for c in catalog["rubric"]["criteria"]}
    for scenario in catalog["scenarios"]:
        if scenario["persona"] not in slugs:
            raise ValueError(f"scenario {scenario['slug']}: unknown persona {scenario['persona']}")
        unknown = set(scenario["applicable_criteria"]) - criteria
        if unknown:
            raise ValueError(f"scenario {scenario['slug']}: unknown criteria {sorted(unknown)}")
    for drill in catalog["drills"]:
        if drill["criterion_id"] not in criteria:
            raise ValueError(f"drill {drill['id']}: unknown criterion {drill['criterion_id']}")
    return personas, catalog


async def seed(dsn: str) -> dict[str, int]:
    personas, catalog = load_seeds()
    conn = await asyncpg.connect(dsn, statement_cache_size=0)
    counts = {"personas_new": 0, "scenarios": 0, "drills": 0, "rubric_new": 0}
    try:
        async with conn.transaction():
            rubric = catalog["rubric"]
            existing = await conn.fetchval(
                "SELECT criteria FROM rubric_versions WHERE version = $1", rubric["version"]
            )
            if existing is None:
                await conn.execute(
                    "INSERT INTO rubric_versions (version, criteria) VALUES ($1, $2::jsonb)",
                    rubric["version"],
                    json.dumps(rubric["criteria"]),
                )
                counts["rubric_new"] = 1
            elif json.loads(existing) != rubric["criteria"]:
                raise RuntimeError(
                    f"{rubric['version']} already exists with different criteria; "
                    "rubric versions are immutable - bump the version instead"
                )

            persona_ids: dict[str, object] = {}
            for p in personas:
                row = await conn.fetchrow(
                    "SELECT id FROM personas WHERE slug = $1 AND prompt_version = $2",
                    p.slug,
                    p.prompt_version,
                )
                if row is None:
                    row = await conn.fetchrow(
                        "INSERT INTO personas (slug, name, title, company, voice, instructions, "
                        "prompt_version) VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING id",
                        p.slug, p.name, p.title, p.company, p.voice, p.instructions,
                        p.prompt_version,
                    )
                    counts["personas_new"] += 1
                persona_ids[p.slug] = row["id"]

            for s in catalog["scenarios"]:
                await conn.execute(
                    """
                    INSERT INTO scenarios (slug, persona_id, rubric_version, title, brief, call_type,
                        difficulty, applicable_criteria, featured, sort_order)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9, $10)
                    ON CONFLICT (slug) DO UPDATE SET
                        persona_id = EXCLUDED.persona_id, rubric_version = EXCLUDED.rubric_version,
                        title = EXCLUDED.title, brief = EXCLUDED.brief,
                        call_type = EXCLUDED.call_type, difficulty = EXCLUDED.difficulty,
                        applicable_criteria = EXCLUDED.applicable_criteria,
                        featured = EXCLUDED.featured, sort_order = EXCLUDED.sort_order
                    """,
                    s["slug"], persona_ids[s["persona"]], rubric["version"], s["title"],
                    s["brief"], s["call_type"], s["difficulty"],
                    json.dumps(s["applicable_criteria"]), s["featured"], s["sort_order"],
                )
                counts["scenarios"] += 1

            for d in catalog["drills"]:
                await conn.execute(
                    """
                    INSERT INTO drills (id, criterion_id, title, instructions)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (id) DO UPDATE SET criterion_id = EXCLUDED.criterion_id,
                        title = EXCLUDED.title, instructions = EXCLUDED.instructions
                    """,
                    d["id"], d["criterion_id"], d["title"], d["instructions"],
                )
                counts["drills"] += 1
    finally:
        await conn.close()
    return counts


def _dsn_from_env() -> str:
    from dotenv import dotenv_values

    env = {**dotenv_values(".env"), **os.environ}
    # Same precedence as Alembic, so the catalog always lands in the database just migrated.
    url = env.get("ALEMBIC_DATABASE_URL") or env.get("ADMIN_DATABASE_URL") or env.get("DATABASE_URL")
    if not url:
        raise SystemExit("set ADMIN_DATABASE_URL, ALEMBIC_DATABASE_URL or DATABASE_URL")
    return make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)


def main() -> int:
    counts = asyncio.run(seed(_dsn_from_env()))
    print(f"catalog seeded: {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
