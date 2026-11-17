"""M4: skills 1-7, market notes, the what's-missing sheet and premise inversion."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from pipeline import runner
from pipeline.adapters.echo import EchoAdapter
from pipeline.adapters.stub_search import StubSearchAdapter

PROJECT_ROOT = Path(__file__).resolve().parents[1]

EARLY_STAGES = (
    "intake",
    "market_research",
    "reference_analysis",
    "setting_research",
    "premise_inversion",
    "theme_premise",
    "tone_ceiling",
)


def project_path(root):
    return root / "projects" / "demo"


def stage_dir(root, number, name):
    return project_path(root) / "stages" / f"{number:02d}-{name}"


def read_meta(root, number, name):
    return json.loads((stage_dir(root, number, name) / "meta.json").read_text(encoding="utf-8"))


def write_concept(root, **values):
    path = project_path(root) / "concept.yaml"
    concept = yaml.safe_load(path.read_text(encoding="utf-8"))
    concept.update(values)
    path.write_text(yaml.safe_dump(concept, sort_keys=False), encoding="utf-8")


def test_every_early_skill_declares_the_expected_frontmatter():
    expected = {
        "intake": (1, False),
        "market_research": (2, True),
        "reference_analysis": (3, True),
        "setting_research": (4, True),
        "premise_inversion": (5, False),
        "theme_premise": (6, False),
        "tone_ceiling": (7, False),
    }

    for name, (number, uses_search) in expected.items():
        skill = runner.load_skill(PROJECT_ROOT, name)
        assert skill.stage == number
        assert skill.uses_search is uses_search
        assert skill.human_gate is False
        assert skill.uses_randomizer is False
        assert skill.model_tier in ("planner", "writer", "checker")


@pytest.mark.parametrize("name", EARLY_STAGES)
def test_each_early_stage_saves_output_and_meta(workspace, name):
    result = runner.run_stage(workspace, "demo", name)

    number = EARLY_STAGES.index(name) + 1
    directory = stage_dir(workspace, number, name)
    assert result.status == runner.DONE
    assert (directory / "output.md").is_file()
    assert (directory / "meta.json").is_file()
    meta = read_meta(workspace, number, name)
    assert meta["stage"] == f"{number:02d}-{name}"
    assert meta["skill"] == name
    assert meta["status"] == "done"
    assert "output.md" in meta["files"]
    assert "meta.json" in meta["files"]


def test_market_research_combines_market_notes_and_search_results(workspace):
    inputs = project_path(workspace) / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    (inputs / "market_notes.md").write_text(
        "# Market notes\n"
        "\n"
        "1. The Lantern Keeper - #2 in Literary Fiction - 12,480 reviews - $4.99\n"
        "2. Salt Harbour - #9 in Literary Fiction - 3,210 ratings - $6.99\n"
        "3. The Quiet Ledger - 840 reviews - $12.99 hardcover\n",
        encoding="utf-8",
    )
    search = StubSearchAdapter(
        {
            "results": [
                {"title": "A comparable review", "url": "https://example.com/r", "snippet": "readers liked the weather"},
                {"title": "Amazon listing", "url": "https://www.amazon.com/dp/1", "snippet": "buy"},
            ]
        }
    )

    result = runner.run_stage(workspace, "demo", "market_research", search=search)

    output = result.output_path.read_text(encoding="utf-8")
    meta = read_meta(workspace, 2, "market_research")
    assert "What's missing" in output
    assert "The Lantern Keeper" in output
    assert "12,480" in output
    assert "$4.99" in output
    assert "https://example.com/r" in output
    assert "amazon.com" not in output.lower()

    assert meta["market_notes"]["found"] is True
    assert meta["market_notes"]["entries"][0]["rank"] == 2
    assert meta["market_notes"]["entries"][0]["reviews"] == 12480
    assert meta["market_notes"]["entries"][0]["price"] == pytest.approx(4.99)
    assert meta["market_notes"]["entries"][2]["price"] == pytest.approx(12.99)
    assert meta["search"]["adapter"] == "stub"
    assert meta["search"]["queries"]
    assert meta["search"]["count"] == 1
    assert meta["whats_missing"]


def test_market_research_without_notes_says_what_to_paste(workspace):
    result = runner.run_stage(workspace, "demo", "market_research")

    output = result.output_path.read_text(encoding="utf-8")
    meta = read_meta(workspace, 2, "market_research")

    assert "What's missing" in output
    assert "inputs/market_notes.md" in output
    assert meta["market_notes"]["found"] is False
    assert any("market_notes.md" in note for note in meta["notes"])
    assert any("market_notes.md" in item for item in meta["whats_missing"])


def test_market_research_flags_a_narrow_price_band(workspace):
    inputs = project_path(workspace) / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    (inputs / "market_notes.md").write_text(
        "1. One - 2,100 reviews - $4.99\n2. Two - 5,400 reviews - $4.99\n3. Three - 8,000 reviews - $5.49\n",
        encoding="utf-8",
    )

    result = runner.run_stage(workspace, "demo", "market_research")

    meta = read_meta(workspace, 2, "market_research")
    assert any("price" in item.lower() for item in meta["whats_missing"])
    assert "price" in result.output_path.read_text(encoding="utf-8").lower()


def test_premise_inversion_lists_expectations_flips_and_market_comparison(workspace):
    write_concept(workspace, genre="cozy mystery")
    market_meta = {
        "comparables": [{"title": "The Lantern Keeper"}, {"title": "Salt Harbour"}]
    }
    market_dir = stage_dir(workspace, 2, "market_research")
    market_dir.mkdir(parents=True)
    (market_dir / "output.md").write_text(
        "# Market research\n\n## Comparables\n- The Lantern Keeper\n- Salt Harbour\n", encoding="utf-8"
    )
    (market_dir / "meta.json").write_text(json.dumps(market_meta), encoding="utf-8")

    result = runner.run_stage(workspace, "demo", "premise_inversion")

    output = result.output_path.read_text(encoding="utf-8")
    meta = read_meta(workspace, 5, "premise_inversion")
    assert "What the genre expects" in output
    assert "What we flip" in output
    assert "Market comparison" in output
    assert "The Lantern Keeper" in output
    assert meta["market_comparison"]["found"] is True
    assert meta["market_comparison"]["comparables"] == ["The Lantern Keeper", "Salt Harbour"]
    assert meta["expectations"]


def test_premise_inversion_without_market_research_says_comparison_is_pending(workspace):
    result = runner.run_stage(workspace, "demo", "premise_inversion")

    output = result.output_path.read_text(encoding="utf-8")
    meta = read_meta(workspace, 5, "premise_inversion")

    assert "What the genre expects" in output
    assert "has not run" in output or "pending" in output.lower()
    assert meta["market_comparison"]["found"] is False


def test_theme_premise_writes_the_central_question(workspace):
    write_concept(
        workspace, genre="literary mystery", premise_seed="a ledger that remembers debts"
    )

    result = runner.run_stage(workspace, "demo", "theme_premise")

    output = result.output_path.read_text(encoding="utf-8")
    meta = read_meta(workspace, 6, "theme_premise")
    assert "Central question" in output
    assert meta["central_question"]
    assert meta["central_question"] in output


def test_tone_ceiling_follows_the_tone_dial(workspace):
    write_concept(workspace, tone_dial=0)
    cozy = runner.run_stage(workspace, "demo", "tone_ceiling")
    cozy_text = cozy.output_path.read_text(encoding="utf-8")
    cozy_meta = read_meta(workspace, 7, "tone_ceiling")
    assert cozy_meta["tone_dial"] == 0
    assert "cozy" in cozy_text.lower()

    write_concept(workspace, tone_dial=3)
    loud = runner.run_stage(workspace, "demo", "tone_ceiling")
    loud_text = loud.output_path.read_text(encoding="utf-8")
    loud_meta = read_meta(workspace, 7, "tone_ceiling")
    assert loud_meta["tone_dial"] == 3
    assert "action-comedy" in loud_text.lower()
    assert cozy_text != loud_text


def test_character_creation_reads_theme_premise_and_tone_from_earlier_stages(workspace):
    write_concept(
        workspace,
        genre="literary mystery",
        premise_seed="a ledger that remembers debts",
        tone_dial=2,
    )
    for name in EARLY_STAGES:
        runner.run_stage(workspace, "demo", name)

    llm = EchoAdapter({"response": "echo"})
    result = runner.run_stage(workspace, "demo", "character_creation", llm=llm)

    prompt = llm.calls[0]["prompt"]
    meta = read_meta(workspace, 8, "character_creation")
    theme = read_meta(workspace, 6, "theme_premise")["central_question"]
    assert "## Story constraints" in prompt
    assert theme in prompt
    assert "a ledger that remembers debts" in prompt
    assert "conflict ceiling" in prompt.lower()
    assert meta["story_constraints"]["theme"] == theme
    assert meta["story_constraints"]["premise"]
    assert meta["story_constraints"]["tone_ceiling"]
    assert not any("missing upstream output: 06" in note for note in meta["notes"])


def test_intake_calls_out_missing_concept_fields(workspace):
    result = runner.run_stage(workspace, "demo", "intake")

    output = result.output_path.read_text(encoding="utf-8")
    meta = read_meta(workspace, 1, "intake")
    assert "Open questions" in output
    assert "premise_seed" in output
    assert "genre" in output
    assert meta["open_questions"]
