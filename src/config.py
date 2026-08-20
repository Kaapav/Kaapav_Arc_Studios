"""Loads config.yaml + .env into one simple object."""
import os
import yaml
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


class Config:
    def __init__(self, config_path: str = "config.yaml"):
        load_dotenv(ROOT / ".env")
        with open(ROOT / config_path, "r", encoding="utf-8") as f:
            self.data = yaml.safe_load(f)

        # ── secrets from environment ──
        self.openai_key = os.getenv("OPENAI_API_KEY", "").strip()
        self.openai_base = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").strip()
        self.openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
        self.llm_timeout = max(10.0, float(os.getenv("LLM_TIMEOUT_SECONDS", "35")))
        self.llm_max_retries = max(0, min(3, int(os.getenv("LLM_MAX_RETRIES", "1"))))
        self.llm_provider = os.getenv("LLM_PROVIDER", "auto").strip().lower()
        self.gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
        self.gemini_base = os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta").strip().rstrip("/")
        self.gemini_model = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite").strip()
        self.qwen_key = os.getenv("QWEN_API_KEY", "").strip()
        self.qwen_base = os.getenv(
            "QWEN_BASE_URL",
            "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        ).strip().rstrip("/")
        self.qwen_model = os.getenv("QWEN_MODEL", "qwen-plus").strip()
        self.deepseek_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        self.deepseek_base = os.getenv(
            "DEEPSEEK_BASE_URL", "https://api.deepseek.com"
        ).strip().rstrip("/")
        self.deepseek_model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash").strip()
        self.groq_key = os.getenv("GROQ_API_KEY", "").strip()
        self.groq_base = os.getenv(
            "GROQ_BASE_URL", "https://api.groq.com/openai/v1"
        ).strip().rstrip("/")
        self.groq_model = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b").strip()
        self.cerebras_key = os.getenv("CEREBRAS_API_KEY", "").strip()
        self.cerebras_base = os.getenv(
            "CEREBRAS_BASE_URL", "https://api.cerebras.ai/v1"
        ).strip().rstrip("/")
        self.cerebras_model = os.getenv("CEREBRAS_MODEL", "gpt-oss-120b").strip()
        fallback_env = os.getenv(
            "LLM_FALLBACKS", "gemini,groq,cerebras,deepseek,openai,qwen"
        )
        self.llm_fallbacks = [x.strip().lower() for x in fallback_env.split(",") if x.strip()]
        self.pexels_key = os.getenv("PEXELS_API_KEY", "").strip()
        self.eleven_key = os.getenv("ELEVENLABS_API_KEY", "").strip()
        self.eleven_voice = os.getenv("ELEVENLABS_VOICE_ID", "").strip()
        self.yt_client_secret = os.getenv("YOUTUBE_CLIENT_SECRET_FILE", "credentials/client_secret.json")
        self.yt_token = os.getenv("YOUTUBE_TOKEN_FILE", "credentials/token.json")
        self.youtube_login_hint = os.getenv("YOUTUBE_LOGIN_HINT", "").strip()
        self.google_sheet_id = os.getenv("GOOGLE_SHEET_ID", "").strip()
        self.google_service_account_file = os.getenv(
            "GOOGLE_SERVICE_ACCOUNT_FILE", ""
        ).strip()

    # convenience accessors -------------------------------------------------
    def __getitem__(self, key):
        return self.data[key]

    def get(self, *keys, default=None):
        """Nested get: cfg.get('video', 'width')."""
        node = self.data
        for k in keys:
            if not isinstance(node, dict) or k not in node:
                return default
            node = node[k]
        return node

    @property
    def has_llm(self):
        return any(profile["key"] for profile in self.llm_profiles().values())

    def llm_profiles(self):
        return {
            "gemini": {"key": self.gemini_key, "base": self.gemini_base,
                       "model": self.gemini_model},
            "openai": {"key": self.openai_key, "base": self.openai_base,
                        "model": self.openai_model},
            "qwen": {"key": self.qwen_key, "base": self.qwen_base,
                      "model": self.qwen_model},
            "deepseek": {"key": self.deepseek_key, "base": self.deepseek_base,
                          "model": self.deepseek_model},
            "groq": {"key": self.groq_key, "base": self.groq_base,
                     "model": self.groq_model},
            "cerebras": {"key": self.cerebras_key, "base": self.cerebras_base,
                         "model": self.cerebras_model},
        }

    def llm_candidates(self):
        """Return configured providers in deterministic primary-to-fallback order."""
        requested = self.llm_provider
        order = []
        if requested not in {"", "auto"}:
            aliases = {"google": "gemini", "compatible": "openai",
                       "openai-compatible": "openai", "dashscope": "qwen"}
            order.append(aliases.get(requested, requested))
        order.extend(self.llm_fallbacks)
        available = self.llm_profiles()
        result = []
        for provider in order:
            if provider in available and available[provider]["key"] and provider not in result:
                result.append(provider)
        return result

    @property
    def active_llm_provider(self):
        candidates = self.llm_candidates()
        return candidates[0] if candidates else "none"

    @property
    def active_llm_key(self):
        provider = self.active_llm_provider
        return self.llm_profiles().get(provider, {}).get("key", "")

    def output_dir(self) -> Path:
        p = ROOT / self.get("paths", "output_dir", default="output")
        p.mkdir(parents=True, exist_ok=True)
        return p

    def cache_dir(self) -> Path:
        p = ROOT / self.get("paths", "cache_dir", default=".cache")
        p.mkdir(parents=True, exist_ok=True)
        return p


if __name__ == "__main__":
    c = Config()
    print("Channel:", c.get("channel", "name"))
    print("LLM enabled:", c.has_llm)
    print("Pexels enabled:", bool(c.pexels_key))
