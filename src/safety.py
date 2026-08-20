"""Content-safety gate — screens the generated script BEFORE it can be published.

Goal: protect the channel from Community-Guideline strikes and advertiser-unfriendly
demonetization, without false-flagging its own EDUCATIONAL topics. This channel talks
about deepfakes, AI voice cloning, "hacking" workflows, scam-detection, etc. — merely
*mentioning* those is fine; the danger is content that *instructs* or *promotes* harm.

Two layers:
  1. High-precision keyword/regex rules — deliberately narrow, aimed at clearly harmful
     phrasing (explicit sexual content, slurs, self-harm encouragement, weapon/drug
     manufacture instructions, real-person impersonation, get-rich scams). We do NOT
     block bare topic words like "deepfake", "hack", "scam", "gun" — those are on-topic.
  2. OpenAI moderation model (nuanced) — used when an LLM key is set; catches subtle cases.

Any flag => report.safe = False. What happens then is decided by `safety.on_fail`
in config ("hold" = keep private for your manual review; "block" = skip entirely).
Default is "hold" so a false positive never deletes a good video — it just waits for you.
"""
import re

# Narrow, intent-focused patterns. Each targets promotion/instruction, not mention.
RULES = {
    "sexual_explicit": [
        r"\b(porn|pornographic|explicit sex|nude photos?|nudes|xxx)\b",
        r"\bsexual(ly)? explicit\b",
    ],
    "self_harm_promo": [
        r"\bhow to (kill|hurt|harm) (yourself|myself)\b",
        r"\b(ways|methods) to (die|self.?harm|commit suicide)\b",
        r"\byou should (kill|harm) yourself\b",
    ],
    "violence_incite": [
        r"\bhow to (kill|murder|attack|hurt) (a |someone|people|him|her|them)\b",
        r"\b(make|build) a (bomb|explosive|weapon)\b",
        r"\bgo shoot up\b",
    ],
    "weapons_drugs_instructions": [
        r"\bhow to (make|synthesi[sz]e|cook|manufacture) (meth|cocaine|heroin|drugs|explosives|a gun)\b",
        r"\b3d.?print(ed)? (gun|firearm)\b.*\b(how to|guide|instructions)\b",
    ],
    "hate_slurs": [
        # kept as a small explicit-slur guard; extend via custom_blocklist if needed.
        r"\b(kill|gas|exterminate) (all )?(jews|muslims|hindus|christians|blacks|whites|gays)\b",
    ],
    "scam_financial": [
        r"\bguaranteed (returns?|profit|income)\b",
        r"\b(get rich quick|double your money|risk.?free investment)\b",
        r"\bsend (me )?(money|crypto) (and|to) (get|receive)\b",
    ],
    "impersonation": [
        r"\bthis is (elon musk|narendra modi|donald trump|the president) speaking\b",
        r"\bofficial statement from (elon|modi|trump|apple|google)\b",
    ],
}

# Advertiser-unfriendly strong profanity (flagged, not necessarily blocked). Keep short.
PROFANITY = [
    "fuck", "motherfucker", "cunt", "bitch", "bastard", "asshole", "dick",
]


def _search_rules(text_lc):
    hits = []
    for category, patterns in RULES.items():
        for pat in patterns:
            if re.search(pat, text_lc):
                hits.append({"category": category, "match": pat, "source": "keyword"})
                break
    return hits


def screen(cfg, narration: str, title: str = "", topic: str = "") -> dict:
    """Return a report: {safe, flags:[...], profanity:[...], moderation, disclosure_needed}."""
    if not cfg.get("safety", "enabled", default=True):
        return {"safe": True, "flags": [], "profanity": [], "moderation": "disabled",
                "disclosure_needed": True, "note": "safety disabled in config"}

    combined = " ".join([topic, title, narration])
    text_lc = combined.lower()

    flags = _search_rules(text_lc)

    # profanity (advertiser-friendliness) — allow common suffixes (fucking, bitches...)
    prof = []
    if cfg.get("safety", "block_profanity", default=True):
        for w in PROFANITY:
            if re.search(rf"\b{re.escape(w)}(s|es|ing|er|ers|ed)?\b", text_lc):
                prof.append(w)

    # user-supplied always-block terms
    for w in (cfg.get("safety", "custom_blocklist", default=[]) or []):
        if w and w.lower() in text_lc:
            flags.append({"category": "custom", "match": w, "source": "custom_blocklist"})

    # nuanced moderation model
    moderation = "skipped"
    if cfg.get("safety", "use_moderation_api", default=True) and cfg.has_llm:
        try:
            from .llm import moderate
            res = moderate(cfg, combined)
            if res is not None:
                flagged, cats = res
                moderation = "flagged" if flagged else "clean"
                if flagged:
                    for c, v in cats.items():
                        if v:
                            flags.append({"category": f"moderation:{c}", "match": "",
                                          "source": "openai_moderation"})
        except Exception as e:
            moderation = f"error: {e}"

    safe = len(flags) == 0 and len(prof) == 0

    return {
        "safe": safe,
        "flags": flags,
        "profanity": prof,
        "moderation": moderation,
        # AI-generated realistic voice/imagery => you should toggle YouTube's
        # "Altered or synthetic content" disclosure. Always true for this pipeline.
        "disclosure_needed": True,
    }
