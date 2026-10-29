import json
from pathlib import Path

import pytest

from app.modules.catalog.seed import SEEDS, load_seeds, parse_persona


def test_all_five_personas_parse_with_a_stable_prompt_version() -> None:
    personas, catalog = load_seeds()
    assert len(personas) == 5 and len(catalog["scenarios"]) == 5
    for p in personas:
        assert p.voice.endswith("Neural") and len(p.prompt_version) == 12
        assert "Never break character" in p.instructions
        assert parse_persona(SEEDS / "personas" / f"{p.slug}.md").prompt_version == p.prompt_version


def test_exactly_one_featured_scenario_and_every_criterion_has_drills() -> None:
    _, catalog = load_seeds()
    assert sum(s["featured"] for s in catalog["scenarios"]) == 1
    criteria = {c["id"] for c in catalog["rubric"]["criteria"]}
    assert len(criteria) == 7
    assert criteria == {d["criterion_id"] for d in catalog["drills"]}


def test_scenario_with_unknown_criterion_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "personas").mkdir()
    for p in (SEEDS / "personas").glob("*.md"):
        (tmp_path / "personas" / p.name).write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
    catalog = json.loads((SEEDS / "catalog.json").read_text(encoding="utf-8"))
    catalog["scenarios"][0]["applicable_criteria"].append("charisma")
    (tmp_path / "catalog.json").write_text(json.dumps(catalog), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown criteria"):
        load_seeds(tmp_path)
