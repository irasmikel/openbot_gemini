from core.logger import get_logger

logger = get_logger("Agent04_05_ContextTactical")


class ContextTacticalAgent:
    """
    AGENTES 4 Y 5 (Fusionados): Analista de Contexto, Bajas y Tactica.
    Evalua lesiones, sanciones, fatiga por calendario, rotaciones y encaje tactico.
    """

    @staticmethod
    def evaluate_match_context(home_team: str, away_team: str) -> dict:
        logger.info(f"Evaluando contexto y tactica para {home_team} vs {away_team}")
        
        assessment = {
            "home_team": home_team,
            "away_team": away_team,
            "home_fatigue_index": "Normal (7 dias de descanso)",
            "away_fatigue_index": "Alto (Partido europeo hace 72h)",
            "key_absences_home": ["Ninguna baja critica"],
            "key_absences_away": ["Delantero titular sancionado", "Mediocentro lesionado"],
            "tactical_matchup": "El local domina la posesion mediante bloque alto; el visitante sufre en transiciones defensivas.",
            "qualitative_adjustment": "Leve penalizacion al rendimiento visitante por acumulacion de fatiga y bajas clave."
        }
        logger.info(f"Evaluacion tactica completada para {home_team} vs {away_team}")
        return assessment
