from pathlib import Path
from typing import Optional
from pydantic import SecretStr, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Directorio raiz del proyecto en Windows
BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Configuracion centralizada y segura del sistema Football Intelligence."""

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # General
    environment: str = Field(default="development", alias="ENVIRONMENT")
    db_path: str = Field(default="data/football_intelligence.db", alias="DB_PATH")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # APIs Deportivas (SecretStr impide que se filtren en logs)
    sportscore_api_key: Optional[SecretStr] = Field(default=None, alias="SPORTSCORE_API_KEY")
    sportscore_host: str = Field(default="sportscore1.p.rapidapi.com", alias="SPORTSCORE_HOST")

    football_data_api_key: Optional[SecretStr] = Field(default=None, alias="FOOTBALL_DATA_API_KEY")
    odds_api_key: Optional[SecretStr] = Field(default=None, alias="ODDS_API_KEY")
    apifootball_api_key: Optional[SecretStr] = Field(default=None, alias="APIFOOTBALL_API_KEY")

    # Modelos IA
    gemini_api_key: Optional[SecretStr] = Field(default=None, alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-2.5-flash", alias="GEMINI_MODEL")

    # Telegram
    telegram_bot_token: Optional[SecretStr] = Field(default=None, alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: Optional[str] = Field(default=None, alias="TELEGRAM_CHAT_ID")

    # Presupuesto maximo diario de llamadas (Control de Costes)
    max_daily_sportscore_calls: int = Field(default=80, alias="MAX_DAILY_SPORTSCORE_CALLS")
    max_daily_odds_api_calls: int = Field(default=15, alias="MAX_DAILY_ODDS_API_CALLS")

    @property
    def full_db_path(self) -> Path:
        return BASE_DIR / self.db_path

    def is_key_configured(self, secret: Optional[SecretStr]) -> bool:
        """Comprueba si una credencial existe y no esta vacia sin exponer su valor."""
        if secret is None:
            return False
        return len(secret.get_secret_value().strip()) > 0


# Instancia global de configuracion
settings = Settings()
