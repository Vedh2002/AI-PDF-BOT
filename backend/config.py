import os
import warnings
from enum import Enum
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Environment(str, Enum):
    LOCAL = "local"
    GCP = "gcp"

# Get environment from env variable, default to local
ENVIRONMENT = os.getenv("ENVIRONMENT", Environment.LOCAL.value)

# Runtime secret lookup (Cloud Run / GCP only):
# value priority is ENV var > Secret Manager secret with same key name > default.
_SM_CLIENT = None
_SM_CACHE: dict[str, str] = {}
_KEY_ALIASES: dict[str, list[str]] = {
    # Backward-compatible alias used by existing deployments.
    "SECRET_KEY": ["JWT_SECRET_KEY"],
}


def _gcp_project_id() -> str:
    return (
        os.getenv("GOOGLE_CLOUD_PROJECT", "")
        or os.getenv("GCP_PROJECT", "")
        or os.getenv("PROJECT_ID", "")
    )


def _get_secret_from_manager(secret_name: str) -> str:
    if ENVIRONMENT != Environment.GCP.value:
        return ""

    if secret_name in _SM_CACHE:
        return _SM_CACHE[secret_name]

    project_id = _gcp_project_id()
    if not project_id:
        return ""

    global _SM_CLIENT
    try:
        if _SM_CLIENT is None:
            from google.cloud import secretmanager
            _SM_CLIENT = secretmanager.SecretManagerServiceClient()

        secret_version_path = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
        response = _SM_CLIENT.access_secret_version(request={"name": secret_version_path})
        value = response.payload.data.decode("utf-8").strip()
        _SM_CACHE[secret_name] = value
        return value
    except Exception:
        return ""


def get_config_value(key: str, default: str = "") -> str:
    env_value = os.getenv(key, "")
    if env_value:
        return env_value

    for alias in _KEY_ALIASES.get(key, []):
        alias_env_value = os.getenv(alias, "")
        if alias_env_value:
            return alias_env_value

    secret_value = _get_secret_from_manager(key)
    if secret_value:
        return secret_value

    for alias in _KEY_ALIASES.get(key, []):
        alias_secret_value = _get_secret_from_manager(alias)
        if alias_secret_value:
            return alias_secret_value

    return default

# Database configuration
if ENVIRONMENT == Environment.GCP.value:
    # GCP Cloud SQL configuration
    DB_USER = get_config_value("DB_USER", "root")
    DB_PASSWORD = get_config_value("DB_PASSWORD", "")
    DB_HOST = get_config_value("DB_HOST", "127.0.0.1")
    DB_PORT = get_config_value("DB_PORT", "3306")
    DB_NAME = get_config_value("DB_NAME", "ai_pdf_bot")

    # Cloud SQL Auth Proxy via Unix socket (used on Cloud Run)
    # Set CLOUD_SQL_CONNECTION_NAME=project:region:instance to enable socket mode
    CLOUD_SQL_CONNECTION_NAME = get_config_value("CLOUD_SQL_CONNECTION_NAME", "")
    if CLOUD_SQL_CONNECTION_NAME:
        DATABASE_URL = (
            f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@/{DB_NAME}"
            f"?unix_socket=/cloudsql/{CLOUD_SQL_CONNECTION_NAME}"
        )
    else:
        # Direct TCP (Cloud SQL with public IP or private VPC)
        DATABASE_URL = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
else:
    # Local SQLite configuration
    # Database file will be stored in backend directory
    DB_PATH = os.getenv("DB_PATH", "./data/ai_pdf_bot.db")
    
    # Ensure data directory exists
    os.makedirs(os.path.dirname(DB_PATH) if os.path.dirname(DB_PATH) else ".", exist_ok=True)
    
    DATABASE_URL = f"sqlite:///{DB_PATH}"

# SQLAlchemy engine configuration
SQLALCHEMY_ECHO = get_config_value("SQLALCHEMY_ECHO", "False").lower() == "true"
SQLALCHEMY_POOL_RECYCLE = int(get_config_value("SQLALCHEMY_POOL_RECYCLE", "3600"))

# JWT Configuration
_secret_key_default = "dev-only-insecure-secret-key-change-in-production"
SECRET_KEY = get_config_value("SECRET_KEY", "")
if not SECRET_KEY:
    if ENVIRONMENT == Environment.GCP.value:
        raise RuntimeError("SECRET_KEY environment variable must be set in production")
    warnings.warn(
        "SECRET_KEY is not set – using an insecure default. Set SECRET_KEY in your .env for local dev.",
        stacklevel=2,
    )
    SECRET_KEY = _secret_key_default
ALGORITHM = get_config_value("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(get_config_value("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))

# CORS Configuration
ALLOWED_ORIGINS = get_config_value("ALLOWED_ORIGINS", "http://localhost:3000").split(",")

# LLM Configuration
# Up to 3 Groq API keys – tried in order; falls back to OpenAI when all are exhausted.
_groq_key_1 = os.getenv("GROQ_API_KEY_1", os.getenv("GROQ_API_KEY", ""))
if not _groq_key_1:
    _groq_key_1 = get_config_value("GROQ_API_KEY_1", get_config_value("GROQ_API_KEY", ""))
_groq_key_2 = get_config_value("GROQ_API_KEY_2", "")
_groq_key_3 = get_config_value("GROQ_API_KEY_3", "")
GROQ_API_KEYS: list[str] = [k for k in [_groq_key_1, _groq_key_2, _groq_key_3] if k]
OPENAI_API_KEY = get_config_value("OPENAI_API_KEY", "")

# Resend Email Configuration
RESEND_API_KEY = get_config_value("RESEND_API_KEY", "")
RESEND_FROM_EMAIL = get_config_value("RESEND_FROM_EMAIL", "aidocchat@hireplz.live")
FRONTEND_URL = get_config_value("FRONTEND_URL", "http://localhost:3000")
GOOGLE_CLIENT_ID = get_config_value("GOOGLE_CLIENT_ID", "")
DEFAULT_LLM_PROVIDER = get_config_value("LLM_PROVIDER", "groq")  # "groq" or "openai"
GROQ_DEFAULT_MODEL = get_config_value("GROQ_MODEL", "openai/gpt-oss-120b")
OPENAI_DEFAULT_MODEL = get_config_value("OPENAI_MODEL", "gpt-4o-mini")
GROQ_VISION_MODEL = get_config_value("GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
OPENAI_VISION_MODEL = get_config_value("OPENAI_VISION_MODEL", "gpt-4o-mini")

# Live web verification configuration
WEB_MIN_CONFIDENCE = int(get_config_value("WEB_MIN_CONFIDENCE", "50"))
WEB_TRUSTED_ONLY = get_config_value("WEB_TRUSTED_ONLY", "false").lower() == "true"

print(f"✓ Environment: {ENVIRONMENT}")
print(f"✓ Database: {DATABASE_URL.split('@')[-1] if '@' in DATABASE_URL else DATABASE_URL}")
print(f"✓ Allowed Origins: {ALLOWED_ORIGINS}")