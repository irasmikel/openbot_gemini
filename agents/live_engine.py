import json
from datetime import datetime, timezone
from typing import Dict, Any, List
from core.logger import get_logger
from core.database import get_db_connection, record_agent_heartbeat

logger = get_logger("Agent07_08_LiveEngine")


class LiveEngineAgent:
    """
    AGENTES 7 Y 8 (Fusionados en Pipeline): Supervisor de Partidos en Directo
    y Detector de Oportunidades en Vivo.
    Vigila el desarrollo del encuentro, calcula el Indice de Presion Ofensiva
    y compara la realidad del partido con las expectativas pre-partido.
    """

    @staticmethod
    def calculate_pressure_index(
        possession: float,
        shots_total: int,
        shots_on_target: int,
        corners: int,
        dangerous_attacks: int = 0
    ) -> float:
        """
        Calcula un Indice de Presion en Vivo (0 a 100) ponderando
        tiros a puerta, tiros totales, corneres, ataques peligrosos y posesion.
        """
        score = (
            (shots_on_target * 9.0) +
            (shots_total * 3.0) +
            (corners * 2.5) +
            (dangerous_attacks * 0.4) +
            (max(0.0, possession - 45.0) * 0.5)
        )
        return round(min(100.0, score), 1)

    @classmethod
    def evaluate_live_match(
        cls,
        match_id: int,
        home_team: str,
        away_team: str,
        minute: int,
        home_score: int,
        away_score: int,
        prematch_fav: str,
        prematch_prob_fav: float,
        prematch_expected_goals: float,
        live_stats: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Evalua las estadisticas en directo frente a las expectativas previas.
        Detecta los escenarios A, B, C y D sin recomendar apuestas automaticas
        si no hay respaldo estadistico suficiente.
        """
        record_agent_heartbeat("AGENT_07_08_LIVE", status="RUNNING")
        logger.info(f"Supervisando en directo: {home_team} {home_score}-{away_score} {away_team} (Min {minute})")

        home_p = cls.calculate_pressure_index(
            live_stats.get("home_possession", 50),
            live_stats.get("home_shots", 0),
            live_stats.get("home_shots_on_target", 0),
            live_stats.get("home_corners", 0),
            live_stats.get("home_dangerous_attacks", 0)
        )
        away_p = cls.calculate_pressure_index(
            live_stats.get("away_possession", 50),
            live_stats.get("away_shots", 0),
            live_stats.get("away_shots_on_target", 0),
            live_stats.get("away_corners", 0),
            live_stats.get("away_dangerous_attacks", 0)
        )

        home_reds = live_stats.get("home_red_cards", 0)
        away_reds = live_stats.get("away_red_cards", 0)
        total_shots_on_target = live_stats.get("home_shots_on_target", 0) + live_stats.get("away_shots_on_target", 0)
        total_goals = home_score + away_score

        detected_alerts = []

        # ESCENARIO A: Favorito claro perdiendo pero dominando claramente en ocasiones
        if prematch_fav == "HOME" and prematch_prob_fav >= 0.55 and home_score < away_score and 20 <= minute <= 70:
            if home_p >= 55.0 and live_stats.get("home_shots_on_target", 0) >= 4 and home_reds == 0:
                remaining_ratio = max(0.1, (90 - minute) / 90.0)
                live_comeback_prob = min(0.75, (prematch_prob_fav * remaining_ratio) + 0.22)
                fair_min_odd = round(1.0 / live_comeback_prob, 2)

                detected_alerts.append({
                    "alert_type": "FAVORITE_TRAILING_DOMINATING",
                    "scenario": "ESCENARIO A: Favorito perdiendo con asedio ofensivo",
                    "situation": f"{home_team} (Favorito previo {prematch_prob_fav*100:.0f}%) pierde {home_score}-{away_score} en el min {minute}, pero acumula un Indice de Presion de {home_p}/100 ({live_stats.get('home_shots_on_target')} tiros a puerta y {live_stats.get('home_corners')} corneres).",
                    "market_focus": "Doble Oportunidad (1X) / Mas de 1.5 o 2.5 goles",
                    "fair_min_odd": fair_min_odd,
                    "confidence": "MEDIA-ALTA",
                    "risks": "Vulnerabilidad a contraataques visitantes si adelanta demasiado la linea defensiva.",
                    "recommendation": f"REVISAR MERCADO 1X si la cuota supera {fair_min_odd}"
                })

        # ESCENARIO B / C: Partido con alta expectativa de goles que sigue 0-0 en min 30-65
        if total_goals == 0 and 28 <= minute <= 65 and prematch_expected_goals >= 2.6:
            if total_shots_on_target >= 5 and (home_p + away_p) >= 75.0:
                detected_alerts.append({
                    "alert_type": "GOALLESS_HIGH_PACE",
                    "scenario": "ESCENARIO B/C: 0-0 enganoso con alto volumen de ocasiones",
                    "situation": f"Marcador 0-0 en el min {minute}, pero ritmo ofensivo muy superior a la media ({total_shots_on_target} tiros a puerta combinados, Presion total {home_p + away_p:.1f}).",
                    "market_focus": "Mas de 0.5 / Mas de 1.5 goles en directo",
                    "fair_min_odd": 1.55,
                    "confidence": "MEDIA",
                    "risks": "Falta de acierto en remate final o actuacion destacada de ambos porteros.",
                    "recommendation": "OPORTUNIDAD EN LINEA DE GOLES (Over 0.5 / 1.5 Live)"
                })
            elif total_shots_on_target <= 1 and (home_p + away_p) <= 30.0:
                detected_alerts.append({
                    "alert_type": "DEAD_PACE_WARNING",
                    "scenario": "ESCENARIO B (Inverso): Prevision alta de goles pero partido bloqueado",
                    "situation": f"Se esperaban {prematch_expected_goals} goles antes del partido, pero en el min {minute} solo hay {total_shots_on_target} tiro a puerta y ritmo muy lento.",
                    "market_focus": "Mercados de goles (Over)",
                    "fair_min_odd": 0.0,
                    "confidence": "ALTA",
                    "risks": "Entrar al Over solo porque la cuota ha subido es un error estadistico: no hay generacion de peligro.",
                    "recommendation": "NO APOSTAR AL OVER (Descartado por falta de ocasiones)"
                })

        # ESCENARIO D: Expulsion (Tarjeta Roja) que altera las probabilidades del partido
        if home_reds > 0 or away_reds > 0:
            team_down = home_team if home_reds > 0 else away_team
            team_up = away_team if home_reds > 0 else home_team
            detected_alerts.append({
                "alert_type": "RED_CARD_SHIFT",
                "scenario": "ESCENARIO D: Superioridad numerica por expulsion",
                "situation": f"Expulsion en {team_down} (Min {minute}, Marcador {home_score}-{away_score}). {team_up} juega con ventaja numerica.",
                "market_focus": f"Victoria o Doble Oportunidad a favor de {team_up}",
                "fair_min_odd": 1.65,
                "confidence": "MEDIA",
                "risks": "Si el equipo con 10 se encierra en bloque bajo y ya va ganando, el mercado suele sobrerreaccionar bajando demasiado la cuota.",
                "recommendation": "VIGILAR ASENTAMIENTO TACTICO (Esperar 5 min tras la roja)"
            })

        # Guardar alertas y actualizar estado en vivo en la base de datos SQLite
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        score_str = f"{home_score}-{away_score}"

        try:
            with get_db_connection() as conn:
                conn.execute("""
                UPDATE matches
                SET status = 'LIVE',
                    minute = ?,
                    home_score = ?,
                    away_score = ?,
                    last_updated_utc = ?
                WHERE match_id = ?;
                """, (minute, home_score, away_score, now_str, match_id))

                for alert in detected_alerts:
                    conn.execute("""
                    INSERT INTO live_alerts (
                        match_id, minute, score_snapshot, alert_type,
                        stats_snapshot_json, analysis_text, sent_to_telegram, created_at_utc
                    ) VALUES (?, ?, ?, ?, ?, ?, 0, ?);
                    """, (
                        match_id,
                        minute,
                        score_str,
                        alert["alert_type"],
                        json.dumps(live_stats),
                        f"{alert['scenario']} | {alert['situation']} -> {alert['recommendation']}",
                        now_str
                    ))
        except Exception as e:
            logger.error(f"Error guardando estado en vivo en SQLite: {e}")

        record_agent_heartbeat("AGENT_07_08_LIVE", status="IDLE")
        return detected_alerts
