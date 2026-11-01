import numpy as np
from scipy.stats import poisson
from core.logger import get_logger

logger = get_logger("Agent02_QuantStats")


class QuantStatsAgent:
    """
    AGENTE 2: Analista Estadístico Previo.
    Calcula la distribución de Poisson y matrices de goles esperados
    para estimar las probabilidades reales de los mercados 1X2 y Goles.
    """

    @classmethod
    def calculate_match_probabilities(cls, lambda_h: float, lambda_a: float, max_goals: int = 6) -> dict:
        """Calcula probabilidades para 1X2 y Over/Under usando distribución de Poisson."""
        logger.info(f"Calculando Poisson con Lambda Local: {lambda_h}, Lambda Visitante: {lambda_a}")

        home_probs = poisson.pmf(np.arange(max_goals + 1), lambda_h)
        away_probs = poisson.pmf(np.arange(max_goals + 1), lambda_a)

        p_home = 0.0
        p_draw = 0.0
        p_away = 0.0

        for h in range(max_goals + 1):
            for a in range(max_goals + 1):
                prob = home_probs[h] * away_probs[a]
                if h > a:
                    p_home += prob
                elif h == a:
                    p_draw += prob
                else:
                    p_away += prob

        total = p_home + p_draw + p_away
        p_home /= total
        p_draw /= total
        p_away /= total

        p_under_25 = 0.0
        for h in range(max_goals + 1):
            for a in range(max_goals + 1):
                if h + a < 2.5:
                    p_under_25 += (home_probs[h] * away_probs[a]) / total
        p_over_25 = 1.0 - p_under_25

        results = {
            "p_home": round(p_home, 4),
            "p_draw": round(p_draw, 4),
            "p_away": round(p_away, 4),
            "p_over_25": round(p_over_25, 4),
            "p_under_25": round(p_under_25, 4)
        }
        logger.info(f"Probabilidades estimadas calculadas: {results}")
        return results