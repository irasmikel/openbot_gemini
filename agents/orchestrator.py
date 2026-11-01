from core.logger import get_logger
from core.database import record_agent_heartbeat, get_db_connection
from agents.dataguard import DataGuardAgent

logger = get_logger("Agent01_Orchestrator")


class OrchestratorAgent:
    """
    AGENTE 1: Coordinador General y Planificador.
    Orquesta el flujo diario de analisis previo y supervisa la salud de los agentes.
    """

    @classmethod
    def run_daily_prematch_pipeline(cls) -> None:
        logger.info("Iniciando pipeline diario de analisis previo...")
        record_agent_heartbeat("AGENT_01_ORCHESTRATOR", status="RUNNING")

        try:
            with get_db_connection() as conn:
                matches = conn.execute("SELECT match_id FROM matches WHERE status = 'SCHEDULED' LIMIT 3;").fetchall()

            if not matches:
                logger.info("No hay partidos programados pendientes de analisis en este momento.")
            else:
                for m in matches:
                    m_id = m["match_id"]
                    if DataGuardAgent.validate_match_data(m_id):
                        logger.info(f"Partido {m_id} validado correctamente por DataGuard.")

            record_agent_heartbeat("AGENT_01_ORCHESTRATOR", status="IDLE")
            logger.info("Pipeline diario de analisis previo finalizado con exito.")
        except Exception as e:
            err_msg = str(e)
            logger.error(f"Error en el pipeline del Coordinador: {err_msg}")
            record_agent_heartbeat("AGENT_01_ORCHESTRATOR", status="ERROR", error_msg=err_msg)
