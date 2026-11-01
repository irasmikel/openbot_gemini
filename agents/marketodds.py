from core.logger import get_logger

logger = get_logger("Agent03_MarketOdds")


class MarketOddsAgent:
    """
    AGENTE 3: Analista de Cuotas y Mercados.
    Extrae el margen de la casa (overround), calcula las cuotas justas (fair odds)
    y determina si existe Valor Esperado positivo (EV > 0).
    """

    @staticmethod
    def analyze_market_value(estimated_prob: float, observed_odd: float) -> dict:
        """
        Calcula el Valor Esperado (EV) de una selección:
        EV = (Probabilidad Estimada * Cuota Observada) - 1
        """
        implied_prob = 1.0 / observed_odd if observed_odd > 1.0 else 1.0
        expected_value = (estimated_prob * observed_odd) - 1.0
        has_value = expected_value > 0.03  # Margen mínimo de valor del 3%

        analysis = {
            "estimated_prob": estimated_prob,
            "observed_odd": observed_odd,
            "implied_prob": round(implied_prob, 4),
            "expected_value": round(expected_value, 4),
            "has_value": has_value,
            "recommendation": "OPORTUNIDAD POTENCIAL" if has_value else "NO APOSTAR (Sin valor suficiente)"
        }
        logger.info(f"Análisis de mercado completado: EV = {expected_value:.2f}, Recomendación = {analysis['recommendation']}")
        return analysis
