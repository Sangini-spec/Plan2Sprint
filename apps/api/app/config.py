from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
import json

_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), extra="ignore")

    # Supabase
    supabase_url: str = "https://your-project.supabase.co"
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    supabase_jwt_secret: str = ""

    # Database
    database_url: str = "postgresql+asyncpg://postgres:password@localhost:5432/postgres"

    # Integrations OAuth
    jira_client_id: str = ""
    jira_client_secret: str = ""
    jira_redirect_uri: str = "http://localhost:8000/api/integrations/jira/auth/callback"
    ado_client_id: str = ""
    ado_client_secret: str = ""
    ado_tenant_id: str = "common"
    ado_redirect_uri: str = "http://localhost:8000/api/integrations/ado/auth/callback"
    github_client_id: str = ""
    github_client_secret: str = ""

    # Slack Integration
    slack_client_id: str = ""
    slack_client_secret: str = ""
    slack_signing_secret: str = ""
    slack_redirect_uri: str = "http://localhost:8000/api/integrations/slack/callback"
    slack_bot_scopes: str = "chat:write,im:write,channels:read,channels:manage,channels:write.invites,groups:write,users:read,users:read.email"

    # Microsoft Teams Integration
    teams_client_id: str = ""
    teams_client_secret: str = ""
    teams_tenant_id: str = "common"
    teams_redirect_uri: str = "http://localhost:8000/api/integrations/teams/callback"

    # Inbound webhook security (Hotfix 80 — security hardening)
    # Each integration's webhook endpoint compares the inbound request
    # signature/secret against the value below. When a secret is empty
    # AND ``strict_webhook_verification`` is True, the endpoint rejects
    # the request with 401 — same behaviour as GitHub's existing strict
    # mode. When the secret is empty AND strict mode is off, we accept
    # but log a [SECURITY] warning so operators see the gap.
    jira_webhook_secret: str = ""           # signs X-Atlassian-Webhook-Signature
    ado_webhook_secret: str = ""            # exact-match X-Hook-Secret header
    teams_webhook_client_state: str = ""    # exact-match clientState in body
    strict_webhook_verification: bool = False

    # AI — Anthropic Claude (legacy)
    anthropic_api_key: str = ""

    # AI — Azure AI Foundry (Grok) — primary model
    azure_ai_api_key: str = ""
    azure_ai_key: str = ""  # alias used in Azure Container Apps
    azure_ai_endpoint: str = ""
    azure_ai_model: str = "grok-4-fast-reasoning"

    # AI — Secondary model (Hotfix 30 — o4-mini on Azure OpenAI).
    # Used as failover when the primary errors out, rate-limits, or times
    # out. Also used directly for high-stakes reasoning calls (rebalancer)
    # where the secondary's reasoning_effort beats the primary's speed.
    # Endpoint URL pattern is ``cognitiveservices.azure.com/openai/...`` —
    # the ai_caller helper auto-detects this and switches request shape
    # (max_completion_tokens, reasoning_effort, no model in body).
    azure_ai_api_key_2: str = ""
    azure_ai_key_2: str = ""
    azure_ai_endpoint_2: str = ""
    azure_ai_model_2: str = "o4-mini"

    # AI — Azure AI Agent Service (agentic workflows)
    azure_agent_endpoint: str = ""
    azure_agent_api_key: str = ""
    azure_agent_model: str = "grok-4-fast-reasoning"

    # Frontend URL (for OAuth redirect back to app)
    frontend_url: str = "http://localhost:3000"

    # Encryption
    integration_encryption_key: str = ""

    # Redis — event bus & distributed locks. Empty = disabled,
    # in-memory fallback.
    #
    # Hotfix 94 — accept two env shapes:
    #   REDIS_URL                     — explicit ``rediss://:<key>@host:port``
    #                                   connection string (preferred when set)
    #   REDIS_ENDPOINT + REDIS_KEY    — Azure Cache for Redis split form
    #                                   (what the Container App env actually
    #                                   plumbs in by default). The validator
    #                                   below composes a ``rediss://:<key>@<endpoint>``
    #                                   URL from these and writes it back to
    #                                   ``redis_url`` so every call site that
    #                                   already reads ``settings.redis_url``
    #                                   keeps working.
    redis_url: str = ""
    redis_endpoint: str = ""
    redis_key: str = ""

    # Sync scheduler — automatic periodic sync for connected tools
    sync_scheduler_enabled: bool = False
    sync_interval_ado: int = 300        # seconds (5 min)
    sync_interval_jira: int = 300       # seconds (5 min)
    sync_interval_github: int = 180     # seconds (3 min)

    # Event stream settings
    event_stream_max_len: int = 10000   # max entries in Redis Stream (MAXLEN ~)

    # Email — SMTP (transactional emails)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_pass: str = ""
    email_from_address: str = "Plan2Sprint <noreply@plan2sprint.app>"

    # App
    cors_origins: str = '["http://localhost:3000"]'
    debug: bool = False

    @property
    def redis_enabled(self) -> bool:
        return bool(self.redis_url)

    def model_post_init(self, __context) -> None:  # noqa: D401
        """Build ``redis_url`` from ``REDIS_ENDPOINT`` + ``REDIS_KEY`` when
        the explicit URL isn't provided.

        Azure Cache for Redis Enterprise (which our Container App points
        at) plumbs in those two env vars but no full URL. Without this
        step ``settings.redis_url`` stays empty, ``redis_enabled`` flips
        to False, and the app silently runs on the in-memory fallback —
        no events propagate across replicas, distributed locks degrade
        to per-process locks.

        TLS (``rediss://``) is required by Azure Cache for Redis on the
        Enterprise / Premium / Standard tiers. Port 10000 is the
        Enterprise default; Basic/Standard use 6380. The endpoint env
        var already includes the port, so we just URL-encode the key
        and slot it in.
        """
        from urllib.parse import quote
        if not self.redis_url and self.redis_endpoint and self.redis_key:
            host_port = self.redis_endpoint.strip()
            if ":" not in host_port:
                host_port = f"{host_port}:10000"  # default Enterprise port
            # URL-encode the key — Azure keys can contain ``=`` and ``/``.
            encoded_key = quote(self.redis_key, safe="")
            self.redis_url = f"rediss://:{encoded_key}@{host_port}"

    @property
    def is_demo_mode(self) -> bool:
        """
        Demo mode when:
        - Supabase URL is missing or placeholder
        - OR JWT secret is missing/placeholder (can't verify tokens)
        """
        url_missing = (
            not self.supabase_url
            or self.supabase_url == "https://your-project.supabase.co"
        )
        jwt_missing = (
            not self.supabase_jwt_secret
            or self.supabase_jwt_secret.startswith("PASTE_")
        )
        return url_missing or jwt_missing

    @property
    def cors_origin_list(self) -> list[str]:
        try:
            return json.loads(self.cors_origins)
        except (json.JSONDecodeError, TypeError):
            return ["http://localhost:3000"]

settings = Settings()
