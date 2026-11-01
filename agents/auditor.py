import math
from datetime import datetime, timezone
from typing import Dict, Any
from core.logger import get_logger
from core.database import get_db_connection, record_agent_heartbeat

logger = get_logger("Agent10_Auditor")


class AuditorAgent:
    """
    AGENTE 10: Evaluador de Resultados y Aprendizaje Estadistico.
    Comprueba las predicciones contra los resultados reales finalizados,
    calcula metricas de calibracion (Brier Score y Log Loss) y genera
    estadisticas acumuladas de ROI, Yield y acierto sin sobreajustar.
    """

    @staticmethod
    def calculate_brier_score(estimated_prob: float, actual_outcome: int) -> float:
        """
        Brier Score = (P_estimada - Resultado_Real)^2
        Rango: 0.0 (perfecto) a 1.0 (peor posible). Un modelo calibrado suele estar < 0.22.
        """
        p = max(0.001, min(0.999, float(estimated_prob)))
        y = 1.0 if actual_outcome == 1 else 0.0
        return round((p - y) ** 2, 4)

    @staticmethod
    def calculate_log_loss(estimated_prob: float, actual_outcome: int) -> float:
        """
        Log Loss = -[y * ln(p) + (1 - y) * ln(1 - p)]
        Penaliza fuertemente el exceso de confianza en pronosticos fallados.
        """
        p = max(0.001, min(0.999, float(estimated_prob)))
        y = 1.0 if actual_outcome == 1 else 0.0
        loss = -(y * math.log(p) + (1.0 - y) * math.log(1.0 - p))
        return round(loss, 4)

    @classmethod
    def settle_prediction(cls, prediction_id: int, actual_outcome: int) -> Dict[str, Any]:
        """Evalua una prediccion registrada (1 = Cumplida, 0 = Fallida) y actualiza SQLite."""
        record_agent_heartbeat("AGENT_10_11_AUDITOR", status="RUNNING")
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        with get_db_connection() as conn:
            pred = conn.execute(
                "SELECT * FROM predictions_audit WHERE prediction_id = ?;",
                (prediction_id,)
            ).fetchone()

            if not pred:
                logger.warning(f"Prediccion {prediction_id} no encontrada para liquidar.")
                record_agent_heartbeat("AGENT_10_11_AUDITOR", status="IDLE")
                return {}

            prob = float(pred["estimated_prob"])
            brier = cls.calculate_brier_score(prob, actual_outcome)
            logloss = cls.calculate_log_loss(prob, actual_outcome)

            conn.execute("""
            UPDATE predictions_audit
            SET actual_outcome = ?,
                brier_score = ?,
                log_loss = ?,
                evaluated_at_utc = ?
            WHERE prediction_id = ?;
            """, (actual_outcome, brier, logloss, now_str, prediction_id))

        record_agent_heartbeat("AGENT_10_11_AUDITOR", status="IDLE")
        logger.info(f"Prediccion {prediction_id} auditada -> Resultado: {actual_outcome}, Brier: {brier}, LogLoss: {logloss}")
        return {
            "prediction_id": prediction_id,
            "actual_outcome": actual_outcome,
            "brier_score": brier,
            "log_loss": logloss
        }

    @classmethod
    def get_global_performance_summary(cls) -> Dict[str, Any]:
        """Calcula metricas acumuladas de calibracion, acierto y Yield teorico."""
        with get_db_connection() as conn:
            rows = conn.execute("""
            SELECT * FROM predictions_audit
            WHERE actual_outcome IS NOT NULL;
            """).fetchall()

        total_evaluated = len(rows)
        if total_evaluated == 0:
            return {
                "total_evaluated": 0,
                "win_rate": 0.0,
                "avg_brier": 0.0,
                "avg_log_loss": 0.0,
                "theoretical_yield": 0.0,
                "theoretical_profit_units": 0.0,
                "sample_warning": "Muestra insuficiente (<200 partidos). No recalibrar parametros."
            }

        hits = sum(1 for r in rows if int(r["actual_outcome"]) == 1)
        avg_brier = sum(float(r["brier_score"] or 0.0) for r in rows) / total_evaluated
        avg_logloss = sum(float(r["log_loss"] or 0.0) for r in rows) / total_evaluated

        # Rentabilidad teorica a stake plano (1 unidad) solo sobre decisiones = 'OPORTUNIDAD'
        opp_rows = [r for r in rows if r["decision"] == "OPORTUNIDAD" and r["observed_odd"]]
        staked_units = len(opp_rows)
        profit_units = 0.0
        for r in opp_rows:
            if int(r["actual_outcome"]) == 1:
                profit_units += (float(r["observed_odd"]) - 1.0)
            else:
                profit_units -= 1.0

        yield_pct = (profit_units / staked_units * 100.0) if staked_units > 0 else 0.0

        return {
            "total_evaluated": total_evaluated,
            "opportunities_taken": staked_units,
            "win_rate": round((hits / total_evaluated) * 100.0, 2),
            "avg_brier": round(avg_brier, 4),
            "avg_log_loss": round(avg_logloss, 4),
            "theoretical_profit_units": round(profit_units, 2),
            "theoretical_yield": round(yield_pct, 2),
            "sample_warning": (
                "Muestra estadistica en construccion (<200 eventos). Prohibido sobreajustar pesos."
                if total_evaluated < 200 else "Muestra estadisticamente significativa."
            )
        }
