from core.logger import get_logger
from core.database import get_db_connection

logger = get_logger("Agent09_DataGuard")


class DataGuardAgent:
    """
    AGENTE 9: Verificador de Datos e Integridad.
    Comprueba que los partidos, equipos y cuotas tengan datos válidos
    y evita que otros agentes procesen información incompleta o desactualizada.
    """

    @staticmethod
    def validate_match_data(match_id: int) -> bool:
        logger.info(f"Validando integridad para el partido ID: {match_id}")
        with get_db_connection() as conn:
            match = conn.execute("SELECT * FROM matches WHERE match_id = ?;", (match_id,)).fetchone()
            if not match:
                logger.warning(f"Validación fallida: Partido ID {match_id} no encontrado.")
                return False

            if not match["home_team_id"] or not match["away_team_id"]:
                logger.warning(f"Validación fallida: Equipos no definidos para partido ID {match_id}.")
                return False

        logger.info(f"Partido ID {match_id} verificado correctamente.")
        return True
