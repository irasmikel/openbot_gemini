from core.logger import get_logger
from core.database import get_db_connection
from datetime import datetime, timezone

logger = get_logger("Agent06_PreMatchDecision")


class PreMatchDecisionAgent:
    """
    AGENTE 6: Detector de Oportunidades Previas.
    Cruza los informes estadisticos (Poisson/Elo), cuotas de mercado (EV)
    y contexto tactico para decidir si existe valor o marcar como NO APOSTAR.
    """

    @staticmethod
    def evaluate_prematch_opportunity(match_id: int, market: str, selection: str, estimated_prob: float, observed_odd: float, context_data: dict) -> dict:
        logger.info(f"Evaluando oportunidad previa para match_id={match_id}, mercado={market}, seleccion={selection}")
        
        implied_prob = 1.0 / observed_odd if observed_odd > 1.0 else 1.0
        expected_value = (estimated_prob * observed_odd) - 1.0
        
        decision = "NO_APOSTAR"
        confidence = "BAJA"
        reasoning = []

        if expected_value > 0.03:
            reasoning.append(f"El modelo estadistico detecta EV positivo (+{expected_value*100:.1f}%).")
            
            if "sancionado" in str(context_data.get("key_absences_away", "")).lower() or "lesionado" in str(context_data.get("key_absences_away", "")).lower():
                reasoning.append("El analista tactico confirma ventaja por bajas del rival.")
                decision = "OPORTUNIDAD"
                confidence = "MEDIA"
            else:
                decision = "VIGILAR"
                confidence = "BAJA"
                reasoning.append("EV positivo pero sin confirmacion tactica solida.")
        else:
            reasoning.append("El valor esperado (EV) no alcanza el umbral minimo de seguridad.")
            decision = "NO_APOSTAR"
            confidence = "ALTA"

        result = {
            "match_id": match_id,
            "market": market,
            "selection": selection,
            "estimated_prob": round(estimated_prob, 4),
            "observed_odd": observed_odd,
            "implied_prob": round(implied_prob, 4),
            "expected_value": round(expected_value, 4),
            "confidence": confidence,
            "decision": decision,
            "reasoning": reasoning
        }

        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        try:
            with get_db_connection() as conn:
                conn.execute("""
                INSERT INTO predictions_audit (
                    match_id, stage, market, selection, estimated_prob, observed_odd,
                    fair_prob_market, expected_value, confidence_level, decision, reasoning_json, created_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, (
                    match_id, "PREMATCH", market, selection, estimated_prob, observed_odd,
                    implied_prob, expected_value, confidence, decision, str(reasoning), now_str
                ))
        except Exception as e:
            logger.error(f"Error guardando auditoria previa en BD: {e}")

        logger.info(f"Decision final tomada: {decision} con confianza {confidence}")
        return result
