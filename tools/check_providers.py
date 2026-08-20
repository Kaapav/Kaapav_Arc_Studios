"""Test every configured LLM independently so a healthy primary cannot hide a dead fallback."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import Config
from src import llm


def main() -> None:
    cfg = Config()
    failures = 0
    configured = [name for name, profile in cfg.llm_profiles().items() if profile["key"]]
    if not configured:
        raise SystemExit("No configured LLM providers")
    for provider in configured:
        cfg.llm_provider = provider
        cfg.llm_fallbacks = []
        try:
            reply = llm.chat(
                cfg,
                "Reply with exactly: READY",
                temperature=0,
                # Reasoning models may spend a few dozen tokens before emitting
                # the visible answer; an 8-token probe can falsely look empty.
                max_tokens=128,
            )
            print(f"[OK]   {provider}/{llm.last_model}: {reply[:20]}")
        except Exception as exc:
            failures += 1
            print(f"[FAIL] {provider}: {str(exc)[:180]}")
    print(f"Configured providers: {len(configured) - failures}/{len(configured)} healthy")
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
