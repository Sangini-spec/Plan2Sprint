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
    slack_bot_scopes: str = "chat:write,im:write,channels:read,users:read,users:read.email"

    # Microsoft Teams Integration
    teams_client_id: str = ""
    teams_client_secret: str = ""
    teams_tenant_id: str = "common"
    teams_redirect_uri: str = "http://localhost:8000/api/integrations/teams/callback"

    # AI — Anthropic Claude (legacy)
    anthropic_api_key: str = ""

    # AI — Azure AI Foundry (Grok)
    azure_ai_api_key: str = ""
    azure_ai_endpoint: str = ""
    azure_ai_model: str = "grok-4-fast-reasoning"

    # AI — Azure AI Agent Service (agentic workflows)
    azure_agent_endpoint: str = ""
    azure_agent_api_key: str = ""
    azure_agent_model: str = "grok-4-fast-reasoning"

    # Frontend URL (for OAuth redirect back to app)
    frontend_url: str = "http://localhost:3000"

    # Encryption
    integration_encryption_key: str = ""

    # Redis — event bus & distributed locks (empty = disabled, in-memory fallback)
    redis_url: str = ""

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
