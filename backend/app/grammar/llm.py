"""Claude-generated exercises. The API key is read from ANTHROPIC_API_KEY, never from code.

Results are cached on disk by (model, topic, type, count, prompt version, topic content): a rerun
costs nothing. --dry-run prints the prompts and makes no call (no key needed).
"""

import hashlib
import json
import os
from pathlib import Path

PROMPT_VERSION = 1
DEFAULT_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")
CACHE_DIR = Path(os.environ.get("GRAMMAR_CACHE", Path(__file__).resolve().parents[2] / "data" / "grammar" / "llm-cache"))

SYSTEM = """You write Spanish grammar exercises for an English-speaking learner at CEFR level {level} (target: B1+ moving to B2).
Rules for every item:
- Natural, neutral Spanish from Spain, one idea per sentence, at most 12 words. No names of real people, no politics, nothing violent, sexual or offensive.
- Everyday vocabulary at or below the learner's level, so the grammar is the only difficulty.
- Exactly one correct answer, unless you list the other valid ones in "alternatives".
- cloze: "text" contains exactly one ____ ; "answer" is what fills it.
- multiple_choice: "text" contains exactly one ____ ; "options" has 3-4 options including the answer; distractors must be clearly wrong in that sentence.
- conjugation: "text" is empty; "prompt" names verb, tense and person; "hint" is the infinitive.
- transformation: "text" is a correct sentence, "prompt" says what to change, "answer" is the full changed sentence.
- error_correction: "text" is a sentence with exactly one grammar error typical of English speakers; "answer" is the full corrected sentence.
- "explanation": one short English sentence naming the rule.
- When the answer is a conjugated verb, fill "verify" (lemma, mood, tense, person, number; compound=true with aux_tense for haber + participle) so it can be checked automatically.
- "natural": false if you are not sure the sentence is idiomatic. "confidence": your honest confidence that the item is correct.
Do not repeat sentences. Call the tool with the items."""

TOOL = {
    "name": "submit_exercises",
    "description": "Submit the generated exercises.",
    "input_schema": {
        "type": "object",
        "properties": {"items": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "type": {"enum": ["cloze", "conjugation", "multiple_choice", "transformation", "error_correction"]},
                "prompt": {"type": "string"}, "text": {"type": "string"}, "answer": {"type": "string"},
                "alternatives": {"type": "array", "items": {"type": "string"}},
                "options": {"type": "array", "items": {"type": "string"}},
                "hint": {"type": "string"}, "explanation": {"type": "string"}, "translation": {"type": "string"},
                "verify": {"type": "object", "properties": {
                    "lemma": {"type": "string"}, "mood": {"enum": ["indicative", "subjunctive", "imperative"]},
                    "tense": {"type": "string"}, "person": {"type": "integer"}, "number": {"enum": ["s", "p"]},
                    "compound": {"type": "boolean"}, "aux_tense": {"type": "string"}}, "required": ["lemma", "mood"]},
                "natural": {"type": "boolean"}, "confidence": {"enum": ["high", "medium", "low"]},
            },
            "required": ["type", "prompt", "answer", "explanation", "natural", "confidence"],
        }}},
        "required": ["items"],
    },
}


def user_prompt(topic: dict, types: list[str], n: int) -> str:
    rules = "\n".join(f"- {r}" for r in topic["key_rules"])
    mistakes = "\n".join(f"- {m}" for m in topic["common_mistakes"])
    return (f"Topic: {topic['title']['en']} ({topic['title']['es']}), level {topic['level']}.\n"
            f"Explanation: {topic['explanation']['en']}\n\nKey rules:\n{rules}\n\nCommon mistakes of English speakers:\n{mistakes}\n\n"
            f"Write {n} exercises, spread across these types: {', '.join(types)}. "
            f"Use the common mistakes for error_correction and plausible distractors.")


def cache_path(topic: dict, types: list[str], n: int, model: str, cache_dir: Path = CACHE_DIR) -> Path:
    content = json.dumps([topic["id"], topic["key_rules"], topic["common_mistakes"], types, n, model, PROMPT_VERSION], sort_keys=True)
    return cache_dir / f"{topic['id']}-{hashlib.sha1(content.encode()).hexdigest()[:10]}.json"


def generate(topic: dict, types: list[str], n: int, *, client=None, model: str = DEFAULT_MODEL,
             cache_dir: Path = CACHE_DIR, dry_run: bool = False) -> tuple[list[dict] | None, str]:
    """Returns (raw items or None, status). status: cached | generated | dry-run."""
    path = cache_path(topic, types, n, model, cache_dir)
    if path.exists():
        return json.loads(path.read_text())["items"], "cached"
    system, user = SYSTEM.format(level=topic["level"]), user_prompt(topic, types, n)
    if dry_run:
        print(f"\n--- dry run: {topic['id']} ({model}) ---\n[system]\n{system}\n\n[user]\n{user}\n--- would write {path.name} ---")
        return None, "dry-run"
    if client is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise SystemExit("ANTHROPIC_API_KEY is not set. Export it, or use --dry-run to preview the prompts.")
        import anthropic
        client = anthropic.Anthropic()
    msg = client.messages.create(
        model=model, max_tokens=8000, system=system, messages=[{"role": "user", "content": user}],
        tools=[TOOL], tool_choice={"type": "tool", "name": TOOL["name"]})
    block = next(b for b in msg.content if getattr(b, "type", None) == "tool_use")
    items = block.input["items"]
    cache_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"model": model, "prompt_version": PROMPT_VERSION, "items": items}, ensure_ascii=False, indent=1))
    return items, "generated"


def to_exercise_dicts(items: list[dict], topic: dict) -> tuple[list[dict], list[tuple[dict, list[str]]]]:
    """Wrap raw LLM items as Exercise dicts. Items the model itself doubts are rejected."""
    good, bad = [], []
    for it in items:
        if it.get("natural") is False:
            bad.append((it, ["model flagged the sentence as not natural"]))
            continue
        base = {k: v for k, v in it.items() if k not in ("natural",)}
        base.update(topic=topic["id"], level=topic["level"], source="llm", source_ids={"model": "llm"},
                    attribution="Generated by Claude; review before trusting",
                    tags=[topic["id"], topic["level"], "grammar", "llm"],
                    notes=["LLM-generated: review"])
        if base.get("verify") is None:
            base.pop("verify", None)
        good.append(base)
    return good, bad
