"""Saturday talking unit: a live Spanish conversation partner on ElevenLabs Agents.

The API key stays here. The phone asks for a short-lived signed WebSocket URL and talks to
ElevenLabs directly. The agent is created on first use and its id is cached in data/talk/agent.json;
the prompt is hashed, so editing it below updates the existing agent instead of creating another.
"""

import hashlib
import json
import os
import random
from pathlib import Path

import httpx

from .podcasts import config

API = "https://api.elevenlabs.io/v1/convai"
DATA = Path(os.environ.get("TALK_DATA", config.ROOT / "backend" / "data" / "talk"))
AGENT_FILE = DATA / "agent.json"
VOICE_ID = os.environ.get("TALK_VOICE_ID") or None          # None = ElevenLabs default voice
TTS_MODEL = os.environ.get("TALK_TTS_MODEL", "eleven_flash_v2_5")   # multilingual, low latency
LLM = os.environ.get("TALK_LLM") or None                     # None = ElevenLabs default LLM

def _sc(id, es, en, goal, starters):
    return {"id": id, "topic": es, "title": en, "goal": goal, "starters": starters}


# topic = what the agent is told to talk about (Spanish); title/goal/starters = guidance shown to the learner (English).
SCENARIOS = [
    _sc("weekend", "tu fin de semana", "Your weekend",
        "Tell a short story in the past: what you did, who with, and how it went.",
        ["Say what you did yesterday, using the preterite and the imperfect.", "Ask your partner what they usually do on Saturdays.", "Describe one thing that went wrong and how you fixed it."]),
    _sc("film", "una película o serie que viste", "A film or series",
        "Recommend something you watched, without spoiling the ending.",
        ["Explain the plot in three sentences.", "Say what you liked or didn't like, and why.", "Ask if your partner would watch it, and why or why not."]),
    _sc("travel", "viajes y vacaciones", "Travel and holidays",
        "Describe a trip you took and plan one you'd like to take.",
        ["Where did you go, and what was the best moment?", "Say where you would go if you had a free month (conditional).", "Ask for advice about a place you want to visit."]),
    _sc("work", "tu trabajo o tus estudios", "Work or studies",
        "Explain what you do and talk about a typical day or a challenge.",
        ["Describe your job or studies and what you like about it.", "Talk about a difficult task and how you handled it.", "Ask about your partner's ideal job."]),
    _sc("food", "comida y restaurantes", "Food and restaurants",
        "Role-play ordering and recommending food, and describe a dish.",
        ["Describe your favourite dish and how it's made.", "Order a meal and ask about the ingredients.", "Complain politely about something that was wrong with a meal."]),
    _sc("city", "tu ciudad y tu barrio", "Your city",
        "Describe where you live and compare it with another place.",
        ["Say what you like and dislike about your neighbourhood.", "Give directions to a place nearby.", "Compare your city with a Spanish-speaking city."]),
    _sc("tech", "tecnología y redes sociales", "Technology and social media",
        "Give and defend an opinion, with reasons.",
        ["Say whether social media is good or bad for people, and why.", "Describe an app you couldn't live without.", "Agree or disagree with your partner using 'creo que' and 'no creo que'."]),
    _sc("health", "deporte y salud", "Sport and health",
        "Talk about habits and give advice.",
        ["Say what exercise you do and how often.", "Give your partner advice for sleeping better (imperative or 'deberías').", "Describe a time you were ill or injured."]),
    _sc("news", "una noticia de esta semana", "A news story",
        "Report what you read and say what you think about it.",
        ["Summarise a story you read this week, using reported speech.", "Say how it could affect people.", "Ask your partner what they think and respond to it."]),
    _sc("childhood", "recuerdos de tu infancia", "Childhood memories",
        "Use the imperfect to describe how things used to be.",
        ["Describe your house or school when you were a child.", "Say what you used to do every summer.", "Tell the story of a memorable day, then ask about your partner's."]),
    _sc("future", "planes para el futuro", "Plans for the future",
        "Talk about plans, hopes and predictions.",
        ["Say what you are going to do next year.", "Say what you hope will happen, using the subjunctive ('espero que').", "Predict how life will be in ten years (future tense)."]),
    _sc("music", "música y conciertos", "Music and concerts",
        "Describe your taste and tell a story about a concert or song.",
        ["Name your favourite artist and explain why.", "Describe a concert or festival you went to.", "Ask your partner to recommend a song in Spanish."]),
    _sc("problem", "un problema cotidiano y cómo lo resolviste", "An everyday problem",
        "Tell a story with a problem, a reaction and a solution.",
        ["Describe a time something broke, got lost or was delayed.", "Explain what you did and how you felt.", "Role-play calling customer service to solve it."]),
]
TOPICS = [s["topic"] for s in SCENARIOS]


FIRST_MESSAGE = "¡Hola! Hoy vamos a hablar de {{topic}}. Tú empiezas: ¿qué me cuentas?"
PROMPT = """Eres un compañero de conversación en español para un estudiante inglés de nivel B1 que quiere llegar a B2.

Tema de hoy: {{topic}}.
Objetivo del estudiante en esta conversación: {{goal}}. Guía la conversación hacia ese objetivo con tus preguntas.
Estructura gramatical de la semana (úsala tú de forma natural y anima al estudiante a usarla): {{focus}}.

Reglas:
- Habla siempre en español, con frases cortas (máximo dos o tres) y a un ritmo claro. Usa vocabulario de nivel B1-B2.
- Haz una sola pregunta cada vez y deja hablar al estudiante; pídele que desarrolle sus respuestas ("¿por qué?", "¿cómo fue?").
- No interrumpas con correcciones largas. Si comete un error importante, repite la frase corregida de forma natural dentro de tu respuesta (por ejemplo: "Ah, ayer fuiste al cine, ¡qué bien!") y sigue.
- Si el estudiante se queda bloqueado o pide ayuda en inglés, di la palabra o frase en español, explícala en una frase sencilla y vuelve a la conversación.
- Si pide un resumen o dice que ha terminado, enumera hasta tres errores que notaste, con la forma correcta, y despídete.
- Sé cálido y curioso. No hables de ti como una IA salvo que te lo pregunten."""


def available() -> bool:
    return bool(config.elevenlabs_key())


def _headers() -> dict:
    return {"xi-api-key": config.elevenlabs_key() or ""}


def agent_config() -> dict:
    tts = {"model_id": TTS_MODEL, **({"voice_id": VOICE_ID} if VOICE_ID else {})}
    prompt = {"prompt": PROMPT, **({"llm": LLM} if LLM else {})}
    return {
        "name": "Spanish talk partner",
        "conversation_config": {
            "agent": {
                "language": "es",
                "first_message": FIRST_MESSAGE,
                "dynamic_variables": {"dynamic_variable_placeholders": {"topic": TOPICS[0], "goal": SCENARIOS[0]["goal"], "focus": "ninguna en particular"}},
                "prompt": prompt,
            },
            "tts": tts,
        },
    }


def _fingerprint(cfg: dict) -> str:
    return hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()[:16]


def _explain(r: httpx.Response) -> RuntimeError:
    try:
        d = r.json().get("detail")
        msg = d.get("message") if isinstance(d, dict) else str(d)
    except Exception:
        msg = r.text[:160]
    return RuntimeError(f"elevenlabs {r.status_code}: {msg}")


def ensure_agent(client: httpx.Client) -> str:
    """The agent id: TALK_AGENT_ID if set, else the cached agent (updated if the config changed), else a new one."""
    if os.environ.get("TALK_AGENT_ID"):
        return os.environ["TALK_AGENT_ID"]
    cfg = agent_config()
    fp = _fingerprint(cfg)
    saved = json.loads(AGENT_FILE.read_text()) if AGENT_FILE.exists() else {}
    if saved.get("agent_id") and saved.get("fingerprint") == fp:
        return saved["agent_id"]
    if saved.get("agent_id"):
        r = client.patch(f"{API}/agents/{saved['agent_id']}", json=cfg, headers=_headers())
    else:
        r = client.post(f"{API}/agents/create", json=cfg, headers=_headers())
    if r.status_code >= 400:
        raise _explain(r)
    agent_id = saved.get("agent_id") or r.json()["agent_id"]
    DATA.mkdir(parents=True, exist_ok=True)
    AGENT_FILE.write_text(json.dumps({"agent_id": agent_id, "fingerprint": fp}))
    return agent_id


def start_session(*, client: httpx.Client | None = None) -> dict:
    """Signed WebSocket URL (valid ~15 min to start) for one conversation."""
    if not available():
        raise RuntimeError("ELEVENLABS_API_KEY is not set")
    own = client or httpx.Client(timeout=20)
    try:
        agent_id = ensure_agent(own)
        r = own.get(f"{API}/conversation/get-signed-url", params={"agent_id": agent_id}, headers=_headers())
        if r.status_code >= 400:
            raise _explain(r)
        return {"signed_url": r.json()["signed_url"]}
    finally:
        if client is None:
            own.close()


def pick_topic(seed: str | None = None) -> str:
    return random.Random(seed).choice(TOPICS) if seed else random.choice(TOPICS)
