"""Stage 13: narrator voice, plus the starter banned-phrase table.

The sentence and paragraph targets come from `craft_targets.json` when it exists and from the
conservative defaults otherwise. The banned phrases live in `tables/banned_phrases.json`, which
this stage creates with a starter list when the table is missing and never overwrites.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from . import craft_targets

STAGE_DIR = "13-narrator_voice"

STARTER_PHRASES: tuple[str, ...] = (
    "a testament to",
    "tapestry of",
    "couldn't help but",
    "little did she know",
    "little did he know",
    "in that moment",
    "a shiver ran down her spine",
    "shivers down her spine",
    "let out a breath she didn't know she was holding",
    "a breath she didn't know she was holding",
    "the air was thick with",
    "eyes widened",
    "barely above a whisper",
    "a single tear rolled down",
    "a symphony of",
    "heart hammered in her chest",
    "heart pounded in her chest",
    "a wave of relief",
    "a wave of nausea",
    "a pang of guilt",
    "a knot in her stomach",
    "a lump in her throat",
    "time seemed to slow",
    "a deafening silence",
    "a pregnant pause",
    "a sea of faces",
    "a myriad of",
    "a whirlwind of",
    "a cascade of",
    "the air crackled with electricity",
    "palpable tension",
    "a flicker of",
    "a ghost of a smile",
    "her breath caught in her throat",
    "his blood ran cold",
    "the world fell away",
    "without a second thought",
    "a heartbeat passed",
    "a knowing smile",
    "her heart skipped a beat",
    "tears pricked her eyes",
    "tears welled in her eyes",
    "a muscle feathered in his jaw",
    "as if on cue",
)

SUBTEXT_GUIDE: tuple[str, ...] = (
    "Every spoken line has an unspoken goal; write the goal, not the emotion.",
    "Emotion arrives as sensation and action, never as a named feeling in a dialogue tag.",
    "A character answers the question they wish they had been asked at least once per scene.",
    "Let the other character misread one line per scene, and let that misreading cost something.",
    "The best line in a scene is usually the one the character decides not to say.",
)


def banned_phrases_path(tables_dir: Path | str) -> Path:
    return Path(tables_dir) / "banned_phrases.json"


def ensure_banned_phrases(
    tables_dir: Path | str, *, notes: list[str] | None = None
) -> list[str]:
    """The table's phrases, creating a starter table when it is missing."""
    notes = notes if notes is not None else []
    path = banned_phrases_path(tables_dir)
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            notes.append(f"{path} is unreadable ({exc}); used the starter phrase list")
            return list(STARTER_PHRASES)
        entries = raw.get("entries") if isinstance(raw, dict) else None
        values = [
            str(entry.get("value") or "").strip()
            for entry in entries or []
            if isinstance(entry, dict) and str(entry.get("value") or "").strip()
        ]
        if values:
            return values
        notes.append(f"{path} has no phrases; used the starter phrase list")
        return list(STARTER_PHRASES)

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "name": "banned_phrases",
        "entries": [
            {"value": phrase, "weight": 1, "tags": ["ai-tell"]} for phrase in STARTER_PHRASES
        ],
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    notes.append(f"created {path} with {len(STARTER_PHRASES)} starter banned phrases")
    return list(STARTER_PHRASES)


def build_voice(
    concept: Mapping[str, Any],
    *,
    targets: craft_targets.Targets | None = None,
    tables_dir: Path | str,
    seed: int,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    notes = notes if notes is not None else []
    sentence_words, sampled_sentences = craft_targets.sample(
        targets, "sentences.words", seed=seed, stage=STAGE_DIR, key="sentence_words"
    )
    paragraph_sentences, sampled_paragraphs = craft_targets.sample(
        targets, "paragraphs.sentences", seed=seed, stage=STAGE_DIR, key="paragraph_sentences"
    )
    dialogue_ratio, _ = craft_targets.sample(
        targets, "dialogue_ratio", seed=seed, stage=STAGE_DIR, key="dialogue_ratio"
    )
    pov, _ = craft_targets.text(targets, "pov")
    tense, _ = craft_targets.text(targets, "tense")

    if not (sampled_sentences and sampled_paragraphs):
        notes.append(
            "no craft_targets.json sentence/paragraph range; used the default targets "
            f"({craft_targets.DEFAULTS['sentences.words']} words, "
            f"{craft_targets.DEFAULTS['paragraphs.sentences']} sentences)"
        )

    return {
        "pov": pov,
        "tense": tense,
        "sentence_words": max(1, int(sentence_words)),
        "paragraph_sentences": max(1, int(paragraph_sentences)),
        "dialogue_ratio": round(float(dialogue_ratio), 3),
        "banned_phrases": ensure_banned_phrases(tables_dir, notes=notes),
        "craft_targets": {
            "path": str(targets.path) if targets is not None else None,
            "sentences": sampled_sentences,
            "paragraphs": sampled_paragraphs,
        },
    }


def render_voice(
    voice: Mapping[str, Any],
    *,
    title: str,
    notes: Sequence[str] = (),
    model_text: str = "",
) -> str:
    lines = [
        f"# Narrator voice - {title}",
        "",
        "## POV and tense",
        "",
        f"- pov: {voice.get('pov')}",
        f"- tense: {voice.get('tense')}",
        "",
        "## Sentence targets",
        "",
        f"- mean sentence: {voice.get('sentence_words')} words",
        "- vary the length: one short sentence after every two long ones",
        "- no more than one em dash per paragraph",
        "",
        "## Paragraph targets",
        "",
        f"- sentences per paragraph: {voice.get('paragraph_sentences')}",
        "- a one-line paragraph is a beat, not a habit",
        "",
        "## Dialogue",
        "",
        f"- dialogue share of the page: {float(voice.get('dialogue_ratio') or 0):.0%}",
        "",
        "## Dialogue subtext guide",
        "",
    ]
    lines.extend(f"- {line}" for line in SUBTEXT_GUIDE)
    lines += ["", "## Banned phrases", "", "- never use these, in narration or dialogue:"]
    lines.extend(f"  - \"{phrase}\"" for phrase in voice.get("banned_phrases") or [])

    if notes:
        lines += ["", "## Notes", ""]
        lines.extend(f"- {note}" for note in notes)
    if model_text.strip():
        lines += ["", "## Planner notes", "", model_text.strip()]
    return "\n".join(lines).rstrip() + "\n"


def voice_prompt(
    skill,
    concept: Mapping[str, Any],
    voice: Mapping[str, Any],
    upstream: str,
    notes: Sequence[str],
) -> str:
    sections = "\n\n".join(f"## {name}\n\n{text}" for name, text in skill.sections.items())
    note_text = "\n".join(f"- {note}" for note in notes) or "- none"
    return (
        f"{sections}\n\n"
        "## This project\n\n"
        f"```yaml\n{yaml.safe_dump(dict(concept), sort_keys=False)}```\n\n"
        "## Voice fixed by code\n"
        f"- pov: {voice.get('pov')}\n"
        f"- tense: {voice.get('tense')}\n"
        f"- mean sentence: {voice.get('sentence_words')} words\n"
        f"- sentences per paragraph: {voice.get('paragraph_sentences')}\n\n"
        "Earlier stage outputs:\n"
        f"{upstream.strip() or '(none yet)'}\n\n"
        "Notes:\n"
        f"{note_text}\n\n"
        "Reply with prose about how the narrator sounds. Do not change the POV, the tense or "
        "the targets; they are fixed.\n"
    )
