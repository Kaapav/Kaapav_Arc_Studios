"""Thin wrapper around any OpenAI-compatible chat API. Optional everywhere.

The `openai` package is imported lazily so users who run template-only (no LLM
key) don't need it installed at all.
"""

_clients = {}
_gemini_models = {}
last_provider = None
last_model = None


def _get_client(cfg, provider="openai"):
    profile = cfg.llm_profiles()[provider]
    key = (provider, profile["base"], cfg.llm_timeout, cfg.llm_max_retries)
    if key not in _clients:
        from openai import OpenAI  # lazy: only needed when an LLM is actually used
        _clients[key] = OpenAI(
            api_key=profile["key"],
            base_url=profile["base"],
            timeout=cfg.llm_timeout,
            max_retries=cfg.llm_max_retries,
        )
    return _clients[key]


def _discover_gemini_model(cfg) -> str:
    """Pick an available generateContent model when Google retires an ID."""
    import requests

    cache_key = (cfg.gemini_base, cfg.gemini_key[-6:])
    if cache_key in _gemini_models:
        return _gemini_models[cache_key]
    response = requests.get(
        f"{cfg.gemini_base}/models",
        params={"key": cfg.gemini_key, "pageSize": 1000},
        timeout=min(cfg.llm_timeout, 25),
    )
    response.raise_for_status()
    available = []
    for item in response.json().get("models", []):
        methods = item.get("supportedGenerationMethods", [])
        if "generateContent" in methods:
            available.append(item.get("name", "").removeprefix("models/"))
    preferences = [
        cfg.gemini_model,
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
        "gemini-2.5-flash-lite",
        "gemini-flash-lite-latest",
        "gemini-2.5-flash",
    ]
    model = next((name for name in preferences if name in available), None)
    if model is None:
        model = next((name for name in available if "flash-lite" in name and "preview" not in name), None)
    if model is None:
        model = next((name for name in available if "flash" in name and "preview" not in name), None)
    if not model:
        raise RuntimeError("Gemini account exposes no generateContent Flash model")
    _gemini_models[cache_key] = model
    return model


def _gemini_chat(cfg, user_prompt: str, system: str, temperature: float,
                 max_tokens: int) -> str:
    """Call Gemini directly using its public REST API (no extra SDK needed)."""
    import requests

    global last_model
    payload = {
        "contents": [{
            "role": "user",
            "parts": [{"text": f"System guidance:\n{system}\n\nUser request:\n{user_prompt}"}],
        }],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        },
    }
    model = cfg.gemini_model
    response = None
    for attempt in range(2):
        url = f"{cfg.gemini_base}/models/{model}:generateContent"
        response = requests.post(
            url,
            params={"key": cfg.gemini_key},
            json=payload,
            timeout=cfg.llm_timeout,
        )
        if response.status_code != 404 or attempt:
            break
        model = _discover_gemini_model(cfg)
        print(f"  [llm] Gemini model changed; auto-selected {model}")
    if response is None or response.status_code >= 400:
        code = response.status_code if response is not None else "no-response"
        detail = response.text.replace("\n", " ")[:240] if response is not None else ""
        raise RuntimeError(f"Gemini HTTP {code}: {detail}")
    data = response.json()
    try:
        reply = "".join(
            part.get("text", "")
            for part in data["candidates"][0]["content"]["parts"]
        ).strip()
        if not reply:
            raise RuntimeError("Gemini returned an empty response")
        last_model = model
        return reply
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Gemini returned no text: {data}") from exc


def _openai_compatible_chat(cfg, provider: str, user_prompt: str, system: str,
                            temperature: float, max_tokens: int) -> str:
    global last_model
    client = _get_client(cfg, provider)
    profile = cfg.llm_profiles()[provider]
    models = [profile["model"]]
    if provider == "groq":
        models.extend(["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.6-27b"])
    elif provider == "cerebras":
        models.extend(["gpt-oss-120b", "qwen-3-235b-a22b-instruct-2507", "llama3.1-8b"])
    models = list(dict.fromkeys(models))
    last_error = None
    for model in models:
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
                **({"max_completion_tokens": max_tokens}
                   if provider == "cerebras" else {"max_tokens": max_tokens}),
            )
            reply = (resp.choices[0].message.content or "").strip()
            if not reply:
                raise RuntimeError("provider returned an empty response")
            last_model = model
            return reply
        except Exception as exc:
            last_error = exc
            status = getattr(exc, "status_code", None)
            message = str(exc).lower()
            model_error = status in {400, 404} and any(
                token in message for token in ("model", "deprecat", "retir", "not found")
            )
            if not model_error or model == models[-1]:
                raise
            print(f"  [llm] {provider} model {model} unavailable; trying replacement")
    raise last_error or RuntimeError(f"{provider} returned no response")


def chat(cfg, user_prompt: str, system: str = "You are a helpful assistant.",
         temperature: float = 0.9, max_tokens: int = 700) -> str:
    """Call configured providers in order; raise only after all have failed."""
    global last_provider, last_model
    last_provider = None
    last_model = None
    if not cfg.has_llm:
        raise RuntimeError("LLM called but no configured LLM key is set.")
    errors = []
    for provider in cfg.llm_candidates():
        try:
            if provider == "gemini":
                reply = _gemini_chat(cfg, user_prompt, system, temperature, max_tokens)
            else:
                reply = _openai_compatible_chat(
                    cfg, provider, user_prompt, system, temperature, max_tokens
                )
            last_provider = provider
            return reply
        except Exception as exc:
            errors.append(f"{provider}: {exc}")
            print(f"  [llm] {provider} failed; trying next fallback ({exc})")
    raise RuntimeError("All configured LLM providers failed: " + " | ".join(errors))


def moderate(cfg, text: str):
    """Run OpenAI's (free) moderation model over `text`.

    Returns (flagged: bool, categories: dict[str,bool]) or None if unavailable.
    Nuanced classifier — far better than keywords at telling an educational mention
    of a topic apart from actually harmful content.
    """
    if not cfg.openai_key:
        return None
    client = _get_client(cfg, "openai")
    try:
        resp = client.moderations.create(model="omni-moderation-latest", input=text)
    except Exception:
        # older/other endpoints may only support the legacy model name
        resp = client.moderations.create(model="text-moderation-latest", input=text)
    result = resp.results[0]
    cats = dict(result.categories) if hasattr(result.categories, "items") else \
        {k: bool(v) for k, v in vars(result.categories).items()}
    return bool(result.flagged), cats
