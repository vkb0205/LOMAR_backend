"""Environment-driven settings (Constitution III: all configuration from env).

No secret, project ID, or model name is committed here — every value is read
from the environment, with only non-sensitive local-development defaults.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- HTTP server (Constitution III: never hardcode the port) ---
    api_host: str = "0.0.0.0"
    api_port: int = 8080

    # --- CORS (Constitution IV: explicit allowlist, never "*") ---
    allowed_origins: str = "http://localhost:3000"

    # --- API documentation exposure. Route security is dependency-based. ---
    enable_auth: bool = False

    # --- Supabase ---
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    supabase_jwt_secret: str = ""
    supabase_jwt_audience: str = "authenticated"
    supabase_jwt_issuer: str = ""
    supabase_jwks_url: str = ""
    supabase_timeout_seconds: float = 8.0

    # Backend-to-Agent Service only. Never expose these through Vite variables.
    agent_service_url: str = ""
    agent_service_internal_key: str = ""
    agent_service_timeout_seconds: float = Field(default=30.0, ge=1.0, le=180.0)

    # --- Google / GenAI (existing AI endpoints, quickstart.md §2) ---
    google_genai_use_vertexai: bool = False
    google_api_key: str = ""
    google_cloud_project: str = ""
    google_cloud_location: str = "global"
    google_text_model: str = "gemini-2.5-flash"

    # --- OpenAI-compatible provider (BI copilot text replies) ---
    # Any provider exposing an OpenAI-compatible /chat/completions API.
    ai_text_provider: str = "openai"
    openai_api_key: str = ""
    # Optional. Leave empty to use the default OpenAI endpoint; set to e.g.
    # https://api.deepseek.com/v1 or a local Ollama gateway to point elsewhere.
    openai_base_url: str = ""
    # Model name verbatim as the provider expects it (e.g. gpt-4o-mini,
    # deepseek-chat, llama3.1).
    ai_text_model: str = ""

    # --- AI consultant agent (tool-calling) ---
    # When false the consultant degrades to a plain single-turn completion with
    # the system prompt but no catalog tools. Lets an operator kill tool access
    # without a redeploy if the provider misbehaves.
    agent_tools_enabled: bool = True
    # Hard ceiling on model->tool->model round trips per request. Prevents a
    # looping model from issuing unbounded database queries (cost + DoS).
    agent_max_tool_iterations: int = Field(default=4, ge=1, le=10)
    # Rows returned to the model per tool call. Kept small: the model only
    # needs enough to recommend, and every row costs context tokens.
    agent_tool_row_limit: int = Field(default=8, ge=1, le=25)
    # Turns of prior conversation accepted from the client. History arrives
    # from an untrusted browser, so it is bounded before reaching the provider.
    agent_max_history_messages: int = Field(default=12, ge=0, le=50)

    # --- Agent session memory (in-process, prototype scope) ---
    session_ttl_seconds: int = Field(default=1800, ge=60, le=86_400)
    # Hard ceiling on concurrently tracked sessions. Memory is process-local
    # and unbounded growth would be a trivial DoS, so the store evicts the
    # least-recently-used session once this is reached.
    session_max_count: int = Field(default=500, ge=1, le=100_000)


    # --- Bounded page sizes (data-model.md invariant 8) ---
    default_page_size: int = Field(default=50, ge=1, le=200)
    max_page_size: int = Field(default=200, ge=1, le=1000)

    @field_validator("supabase_url")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @property
    def allowed_origins_list(self) -> list[str]:
        """Parse the comma-separated allowlist.

        A literal "*" is rejected at the app layer rather than silently
        widening CORS (Constitution IV).
        """
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]

    @property
    def supabase_issuer(self) -> str:
        return self.supabase_jwt_issuer

    @property
    def supabase_jwks_endpoint(self) -> str:
        return self.supabase_jwks_url or (
            f"{self.supabase_url}/auth/v1/.well-known/jwks.json"
            if self.supabase_url else ""
        )

    @property
    def supabase_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_anon_key)

    @property
    def vertex_configured(self) -> bool:
        return bool(self.google_genai_use_vertexai and self.google_cloud_project)

@lru_cache
def get_settings() -> Settings:
    """Process-wide settings.

    Cached for import cost only; the object is immutable configuration, not
    request state, so this does not violate Constitution III's statelessness
    requirement.
    """
    return Settings()
