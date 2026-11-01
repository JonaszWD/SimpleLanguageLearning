"""Optional comprehension self-check: 3 questions about a segment, written by Claude.

Key from ANTHROPIC_API_KEY (never hardcoded). Cached on disk by the segment text, so a repeat is free.
Every question is marked source: "llm". --dry-run style preview via dry_run=True.
"""

import hashlib
import json
import os
from pathlib import Path

from . import config

PROMPT_VERSION = 1
MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")
CACHE = config.DATA_DIR / "questions"

SYSTEM = """You write listening-comprehension questions for an English-speaking Spanish learner (about B1+/B2).
Given a transcript segment, write exactly 3 multiple-choice questions in simple Spanish about the main ideas,
not trivia. Each question has 3 options, exactly one correct, and a one-sentence English explanation quoting what
was said. Use only what the transcript says. Call the tool."""

TOOL = {
    "name": "submit_questions",
    "description": "Submit the comprehension questions.",
    "input_schema": {"type": "object", "properties": {"questions": {"type": "array", "minItems": 3, "maxItems": 3, "items": {
        "type": "object", "properties": {
            "question": {"type": "string"}, "options": {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 3},
            "correct": {"type": "integer", "minimum": 0, "maximum": 2}, "explanation": {"type": "string"}},
        "required": ["question", "options", "correct", "explanation"]}}}, "required": ["questions"]},
}


def cache_path(text: str, model: str = MODEL, directory: Path | None = None) -> Path:
    directory = directory or CACHE
    h = hashlib.sha1(json.dumps([text, model, PROMPT_VERSION]).encode()).hexdigest()[:16]
    return directory / f"{h}.json"


def valid(q: dict) -> bool:
    return (isinstance(q.get("options"), list) and len(q["options"]) == 3 and len(set(q["options"])) == 3
            and q.get("correct") in (0, 1, 2) and q.get("question", "").strip() and q.get("explanation", "").strip())


def generate(text: str, *, client=None, model: str = MODEL, directory: Path | None = None, dry_run: bool = False) -> dict | None:
    directory = directory or CACHE
    path = cache_path(text, model, directory)
    if path.exists():
        return {**json.loads(path.read_text()), "cached": True}
    if dry_run:
        print(f"[system]\n{SYSTEM}\n\n[user]\nTranscript segment:\n{text[:1500]}\n--- would write {path.name} ---")
        return None
    if client is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        import anthropic
        client = anthropic.Anthropic()
    msg = client.messages.create(model=model, max_tokens=1500, system=SYSTEM, tools=[TOOL],
                                 tool_choice={"type": "tool", "name": TOOL["name"]},
                                 messages=[{"role": "user", "content": f"Transcript segment:\n{text[:12000]}"}])
    block = next(b for b in msg.content if getattr(b, "type", None) == "tool_use")
    qs = [q for q in block.input["questions"] if valid(q)]
    if len(qs) < 3:
        raise ValueError("the model returned invalid questions")
    data = {"source": "llm", "model": model, "questions": [{**q, "source": "llm"} for q in qs]}
    directory.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    return data
