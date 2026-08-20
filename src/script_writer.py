"""Turn a topic into a full content package built to go viral AND build loyalty:
   narration text, per-scene visual keywords, title, description, tags.

Virality comes from structure (a scroll-stopping hook -> tension -> payoff, plus an
optional loop back to the hook to boost re-watches). Loyalty comes from a consistent
persona, a recurring series framing, and a signature sign-off. Both are driven by the
`brand` and `script` sections of config.yaml.

With an LLM key -> rich, on-brand scripts. Without a key -> a clean branded template.
"""
import json
import re
import hashlib
from .llm import chat


LANG_INSTRUCTION = {
    "hindi": "Write the narration in natural conversational Hindi (Devanagari script).",
    "english": "Write the narration in punchy, natural, conversational English (global audience).",
    "hinglish": "Write the narration in Hinglish — Hindi spoken naturally but written in "
                "Roman/English letters, the way young people actually talk on Reels.",
}


def _extract_json(text: str) -> dict:
    """LLMs sometimes wrap JSON in prose or ```json fences. Be forgiving."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1:
        text = text[start:end + 1]
    return json.loads(text)


def _pick_series(cfg, topic: str):
    series = cfg.get("brand", "series", default=[]) or []
    if not series or not cfg.get("script", "use_series", default=True):
        return None
    # stable hash so a given topic always maps to the same series framing across runs
    idx = int(hashlib.md5(topic.encode()).hexdigest(), 16) % len(series)
    return series[idx]


def _fit_title(cfg, title: str, fallback: str) -> str:
    """Keep titles within YouTube's limit without cutting a word in half."""
    limit = int(cfg.get("youtube", "title_max", default=90) or 90)
    clean = re.sub(r"\s+", " ", (title or fallback).strip())
    if len(clean) <= limit:
        return clean
    clipped = clean[:limit + 1].rsplit(" ", 1)[0].rstrip(" |:,-")
    return clipped or clean[:limit]


def write_script(cfg, topic: str) -> dict:
    lang = cfg.get("channel", "language", default="english")
    target_words = cfg.get("script", "target_words", default=120)
    n_scenes = cfg.get("script", "scenes", default=6)
    cta = cfg.get("channel", "cta", default="")
    channel = cfg.get("channel", "name", default="")

    if cfg.has_llm:
        try:
            result = _llm_script(cfg, topic, lang, target_words, n_scenes, cta, channel)
        except Exception as exc:
            # Keep the queue alive, but mark degraded drafts so they cannot
            # silently become public content.
            print(f"      [script] all LLM providers failed ({exc}); using held fallback draft")
            result = _template_script(cfg, topic, n_scenes, cta, channel)
            result["_fallback_mode"] = "template"
    else:
        result = _template_script(cfg, topic, n_scenes, cta, channel)
        result["_fallback_mode"] = "template"
    result["title"] = _fit_title(cfg, result.get("title"), topic)
    return result


def _llm_script(cfg, topic, lang, target_words, n_scenes, cta, channel) -> dict:
    lang_note = LANG_INSTRUCTION.get(lang, LANG_INSTRUCTION["english"])
    persona = cfg.get("brand", "persona", default="a friendly, high-energy creator")
    signoff = cfg.get("brand", "signoff", default=cta)
    catchphrase = cfg.get("brand", "catchphrase", default="")
    series = _pick_series(cfg, topic)
    viral = cfg.get("script", "viral_mode", default=True)
    loop = cfg.get("script", "loop_ending", default=True)

    series_note = f'- Frame this as an episode of the recurring series "{series}".' if series else ""
    catch_note = (f'- Open in the spirit of the channel catchphrase "{catchphrase}" '
                  f'(adapt it, do not paste it robotically).') if catchphrase else ""
    loop_note = ("- Make the FINAL line echo/callback the opening hook so the Short loops "
                 "seamlessly and viewers re-watch.") if loop else ""
    viral_note = (
        "- STRUCTURE for virality: (1) a scroll-stopping hook in the first 3 seconds — a bold "
        "claim, a 'you've been doing X wrong', or an open loop question; (2) escalating tension / "
        "curiosity gap; (3) a genuinely useful or surprising PAYOFF; (4) the sign-off.\n"
        "- Every sentence must earn the next one. No throat-clearing, no 'in this video'."
    ) if viral else ""

    prompt = f"""
You are {persona}, scripting a faceless YouTube Short for the channel "{channel}".
TOPIC: {topic}

Rules:
- {lang_note}
{catch_note}
{series_note}
{viral_note}
- Total narration ~{target_words} words, fast and tight.
- This must feel like a real mini-story, not a slideshow, news summary, or listicle.
- Use ONE protagonist with ONE concrete problem and ONE visible result. If the topic names
  several tools, choose one tool and one outcome; do not dump a list of products.
- Build the beats as: instant hook -> problem -> failed attempt or doubt -> discovery ->
  visible before/after -> honest verdict -> unresolved question or cliffhanger.
- Each scene must contain a new physical action or change of location, not a new paragraph
  over the same background. Write visuals that can be shown as moving stock footage.
- Add ONE original opinion, verdict, or hot take — this is what keeps the channel authentic
  and monetizable (YouTube demonetizes generic, template-feeling AI content).
- End with this call to action, rephrased naturally in the channel voice: "{signoff or cta}".
{loop_note}
- Break the narration into exactly {n_scenes} short scenes.
- For each scene give a 2-6 word on-screen caption (not the narration), plus 2-4 ENGLISH
  stock-search keywords for a matching MOVING clip (concrete + visual, e.g. "tired creator
  editing video at night", "phone notification close-up", "fast video editing timeline").
- Write a viral TITLE (<= 90 chars, curiosity-driven, may use 1 emoji) and a DESCRIPTION
  (2-3 lines + 5 relevant hashtags).

SAFETY (non-negotiable — protects the channel from strikes and demonetization):
- Family-friendly and advertiser-friendly: no profanity, no sexual content, no graphic
  violence, no dangerous instructions, nothing hateful or harassing.
- No medical, financial, or legal advice presented as certainty; no "guaranteed money",
  miracle-cure, or fear-bait claims. Curiosity yes, deception no.
- Only make factual claims you are confident are true; if uncertain, say "reportedly"
  or frame it as an open question. Never invent statistics.
- Never present AI-generated voices/faces as real people; no impersonation of real
  public figures. Be honest that AI tools are being demonstrated.

Return ONLY valid JSON:
{{
  "title": "...",
  "description": "...",
  "series": "{series or ''}",
  "narration": "full narration, scenes separated by newlines",
  "scenes": [
    {{"text": "scene 1 narration", "caption": "short visual beat", "keywords": "english visual keywords"}}
    // exactly {n_scenes} items
  ],
  "tags": ["tag1","tag2","..."]
}}
"""
    raw = chat(cfg, prompt,
               system="You are an award-winning short-form scriptwriter who reliably makes videos go viral while keeping a consistent, lovable channel persona.",
               temperature=0.9, max_tokens=1300)
    data = _extract_json(raw)

    data.setdefault("tags", [])
    data["title"] = _fit_title(cfg, data.get("title"), topic)
    scenes = data.get("scenes") or []
    if not scenes:
        parts = [p.strip() for p in re.split(r"[\n.]", data.get("narration", "")) if p.strip()]
        scenes = [{"text": p, "keywords": topic} for p in parts[:n_scenes]]
    data["scenes"] = scenes
    if not data.get("narration"):
        data["narration"] = " ".join(s["text"] for s in scenes)
    return data


def _template_script(cfg, topic, n_scenes, cta, channel) -> dict:
    """Zero-API fallback. Branded and structured, but the LLM path is far stronger —
    don't publish template-only videos long-term (they read as mass-produced)."""
    signoff = cfg.get("brand", "signoff", default=cta or "Subscribe for more!")
    series = _pick_series(cfg, topic) or ""

    hook = f"You're probably using AI wrong — and {topic.lower()} proves it."
    body = [
        f"Here's what almost nobody tells you about {topic.lower()}.",
        "I tested it myself so you don't have to.",
        "The result honestly surprised me.",
        "And it changes how you'd actually use this.",
        "My verdict? Worth trying today.",
    ]
    caption_labels = ["The hidden problem", "I tested it", "Unexpected result",
                      "The real difference", "My honest verdict"]
    scenes = [{"text": hook, "caption": "You are using AI wrong", "keywords": f"{topic} artificial intelligence"}]
    for i in range(max(1, n_scenes - 2)):
        scenes.append({"text": body[i % len(body)], "caption": caption_labels[i % len(caption_labels)],
                       "keywords": "ai technology futuristic screen"})
    scenes.append({"text": signoff, "caption": "Follow for tomorrow's test",
                   "keywords": "subscribe button youtube glowing"})
    narration = " ".join(s["text"] for s in scenes)

    title_tail = f" | {series}" if series else f" | {channel}"
    return {
        "title": f"You're using AI wrong: {topic} 🤯{title_tail}"[:90],
        "series": series,
        "description": f"{topic}\n\n{series or 'AI Creative Explorer'} — testing AI so you don't have to.\n\n#ai #aitools #aiart #shorts #tech",
        "narration": narration,
        "scenes": scenes,
        "tags": ["ai", "aitools", "aiart", "shorts", "tech"],
    }
