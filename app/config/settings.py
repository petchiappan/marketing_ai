"""Application settings loaded from environment variables."""

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Central configuration – reads from .env or environment variables."""

    # ── Database ──
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/marketing_ai",
        alias="DATABASE_URL",
    )

    # ── Redis ──
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")

    # ── JWT / Auth ──
    jwt_secret_key: str = Field(default="change-me", alias="JWT_SECRET_KEY")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    jwt_expire_hours: int = Field(default=8, alias="JWT_EXPIRE_HOURS")

    # ── Azure AD OIDC ──
    azure_ad_tenant_id: str = Field(default="", alias="AZURE_AD_TENANT_ID")
    azure_ad_client_id: str = Field(default="", alias="AZURE_AD_CLIENT_ID")
    azure_ad_client_secret: str = Field(default="", alias="AZURE_AD_CLIENT_SECRET")
    azure_ad_redirect_uri: str = Field(
        default="http://localhost:8000/admin/auth/azure/callback",
        alias="AZURE_AD_REDIRECT_URI",
    )

    # ── Encryption key for tool API secrets ──
    tool_secret_encryption_key: str = Field(
        default="", alias="TOOL_SECRET_ENCRYPTION_KEY"
    )

    # ── Default admin ──
    default_admin_email: str = Field(
        default="admin@localhost", alias="DEFAULT_ADMIN_EMAIL"
    )
    default_admin_password: str = Field(
        default="changeme123", alias="DEFAULT_ADMIN_PASSWORD"
    )

    # ── Salesforce ──
    salesforce_username: str = Field(default="", alias="SALESFORCE_USERNAME")
    salesforce_password: str = Field(default="", alias="SALESFORCE_PASSWORD")
    salesforce_security_token: str = Field(
        default="", alias="SALESFORCE_SECURITY_TOKEN"
    )
    salesforce_domain: str = Field(default="login", alias="SALESFORCE_DOMAIN")

    # ── LLM ──
    llm_provider: str = Field(default="openai", alias="LLM_PROVIDER")
    llm_model: str = Field(default="gpt-4o-mini", alias="LLM_MODEL")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    google_api_key: str = Field(default="", alias="GOOGLE_API_KEY")
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")

    # ── Groq ──
    groq_api_key: str = Field(default="", alias="GROQ_API_KEY")
    groq_base_url: str = Field(default="https://api.groq.com/openai/v1", alias="GROQ_BASE_URL")
    groq_model: str = Field(default="openai/gpt-oss-20b", alias="GROQ_MODEL")

    # SSL verification (set True only if behind corporate proxy / self-signed certs)
    disable_ssl_verification: bool = Field(default=False, alias="DISABLE_SSL_VERIFICATION")

    @property
    def llm_identifier(self) -> str:
        """Return the CrewAI / LiteLLM compatible model string: 'provider/model'."""
        return f"{self.llm_provider}/{self.llm_model}"

    # Backward compat alias
    @property
    def openai_model_name(self) -> str:
        return self.llm_identifier

    # ── Cache TTLs (seconds) ──
    cache_ttl_contacts: int = 86_400   # 24 h
    cache_ttl_news: int = 14_400       # 4 h
    cache_ttl_financial: int = 43_200  # 12 h
    cache_ttl_metadata: int = 604_800  # 7 d

    # ── LLM Response Cache ──
    llm_cache_enabled: bool = Field(default=True, alias="LLM_CACHE_ENABLED")
    llm_cache_ttl_hours: int = Field(default=24, alias="LLM_CACHE_TTL_HOURS")

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

settings = Settings()
