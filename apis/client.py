import httpx
from typing import Optional, Dict, Any
from core.config import settings
from core.logger import get_logger
from core.database import get_db_connection
from datetime import datetime, timezone

logger = get_logger("APIClient")


class SportsAPIClient:
    """
    Cliente HTTP unificado para gestionar las consultas a las APIs externas
    respetando los límites y registrando el consumo diario en SQLite.
    """

    @staticmethod
    def _log_usage(provider: str, endpoint: str, status_code: int) -> None:
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        try:
            with get_db_connection() as conn:
                conn.execute("""
                INSERT INTO api_usage_log (provider, endpoint, status_code, called_date_utc, called_timestamp_utc)
                VALUES (?, ?, ?, ?, ?);
                """, (provider.upper(), endpoint, status_code, today_str, now_ts))
        except Exception as e:
            logger.error(f"Error registrando uso de API: {e}")

    @classmethod
    def fetch_football_data_standings(cls, competition_code: str) -> Optional[Dict[str, Any]]:
        """Consulta la clasificación y partidos desde football-data.org (Plan Gratuito)."""
        if not settings.is_key_configured(settings.football_data_api_key):
            logger.warning("football-data.org API key no configurada.")
            return None

        url = f"https://api.football-data.org/v4/competitions/{competition_code}/standings"
        headers = {"X-Auth-Token": settings.football_data_api_key.get_secret_value()}

        try:
            with httpx.Client(timeout=15.0) as client:
                response = client.get(url, headers=headers)
                cls._log_usage("FOOTBALL_DATA", f"/competitions/{competition_code}/standings", response.status_code)
                if response.status_code == 200:
                    return response.json()
                else:
                    logger.error(f"Error football-data.org ({response.status_code}): {response.text}")
                    return None
        except Exception as e:
            logger.error(f"Excepción conectando a football-data.org: {e}")
            return None

    @classmethod
    def fetch_odds_prematch(cls, odds_api_sport_key: str) -> Optional[list]:
        """Consulta las cuotas pre-partido desde The Odds API."""
        if not settings.is_key_configured(settings.odds_api_key):
            logger.warning("The Odds API key no configurada.")
            return None

        url = f"https://api.the-odds-api.com/v4/sports/{odds_api_sport_key}/odds/"
        params = {
            "apiKey": settings.odds_api_key.get_secret_value(),
            "regions": "eu",
            "markets": "h2h,totals",
            "oddsFormat": "decimal"
        }

        try:
            with httpx.Client(timeout=15.0) as client:
                response = client.get(url, params=params)
                cls._log_usage("ODDS_API", f"/sports/{odds_api_sport_key}/odds", response.status_code)
                if response.status_code == 200:
                    return response.json()
                else:
                    logger.error(f"Error The Odds API ({response.status_code}): {response.text}")
                    return None
        except Exception as e:
            logger.error(f"Excepción conectando a The Odds API: {e}")
            return None
