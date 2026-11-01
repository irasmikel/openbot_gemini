import sys
from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.logger import get_logger
from core.database import init_database, get_db_connection
from agents.telegram_reporter import TelegramReporterAgent
from scripts.sync_real_matches import (
    ensure_standings_table,
    sync_standings_and_matches_football_data,
    sync_real_odds_from_the_odds_api,
    run_real_statistical_analysis
)

logger = get_logger("GitHubRunner")
LOCAL_TZ = ZoneInfo("Europe/Madrid")


def format_kickoff_local(utc_str: str) -> str:
    if not utc_str:
        return "Pendiente"
    try:
        clean = utc_str.strip().replace("T", " ").replace("Z", "")[:19]
        dt_utc = datetime.strptime(clean, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        dt_loc = dt_utc.astimezone(LOCAL_TZ)
        return dt_loc.strftime("%d/%m %H:%M") + "h"
    except Exception:
        return utc_str[:16]


def ensure_telegram_tracking_table() -> None:
    """Tabla para recordar que oportunidades previas ya se enviaron a Telegram y no repetir."""
    with get_db_connection() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS prematch_sent_alerts (
            match_id INTEGER NOT NULL,
            market TEXT NOT NULL,
            selection TEXT NOT NULL,
            sent_at_utc TEXT NOT NULL,
            PRIMARY KEY (match_id, market, selection)
        );
        """)


def run_cloud_cycle() -> None:
    logger.info("=== INICIANDO CICLO AUTONOMO EN GITHUB ACTIONS ===")
    init_database()
    ensure_standings_table()
    ensure_telegram_tracking_table()

    # 1. Limpiar posibles datos sinteticos residuales (solo si existen IDs de prueba)
    with get_db_connection() as conn:
        conn.execute("DELETE FROM matches WHERE football_data_match_id IS NULL OR football_data_match_id < 10000;")

    # 2. Sincronizar clasificaciones, partidos y cuotas reales
    m_count = sync_standings_and_matches_football_data()
    o_count = sync_real_odds_from_the_odds_api()
    run_real_statistical_analysis()

    logger.info(f"Sincronizacion completada: {m_count} partidos y {o_count} cuotas reales.")

    # 3. Buscar nuevas OPORTUNIDADES (EV+) que aun no se hayan notificado por Telegram
    with get_db_connection() as conn:
        opps = conn.execute("""
        SELECT p.match_id, c.name as liga, t1.canonical_name as local, t2.canonical_name as visitante,
               m.kickoff_utc, p.market, p.selection, p.estimated_prob, p.observed_odd,
               p.expected_value, p.confidence_level, p.reasoning_json
        FROM predictions_audit p
        JOIN matches m ON p.match_id = m.match_id
        JOIN competitions c ON m.competition_code = c.canonical_code
        JOIN teams t1 ON m.home_team_id = t1.team_id
        JOIN teams t2 ON m.away_team_id = t2.team_id
        LEFT JOIN prematch_sent_alerts s
          ON p.match_id = s.match_id AND p.market = s.market AND p.selection = s.selection
        WHERE p.decision = 'OPORTUNIDAD'
          AND m.status = 'SCHEDULED'
          AND s.match_id IS NULL
        ORDER BY p.expected_value DESC;
        """).fetchall()

    if not opps:
        logger.info("No hay oportunidades nuevas pendientes de notificar en este ciclo.")
        return

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    lines = ["⚽ FOOTBALL INTELLIGENCE CLOUD - NUEVAS OPORTUNIDADES (EV+):", ""]

    for row in opps:
        hora_es = format_kickoff_local(row["kickoff_utc"])
        sel_map = {
            "HOME": f"Gana {row['local']} (1)",
            "AWAY": f"Gana {row['visitante']} (2)",
            "DRAW": "Empate (X)"
        }
        sel_txt = sel_map.get(row["selection"], row["selection"])
        prob_pct = float(row["estimated_prob"]) * 100.0
        fair_odd = 1.0 / float(row["estimated_prob"])
        ev_pct = float(row["expected_value"]) * 100.0

        lines.append(f"🏆 {row['liga']} | 🕒 {hora_es}")
        lines.append(f"⚔️ {row['local']} vs {row['visitante']}")
        lines.append(f"🎯 Pronostico: {sel_txt}")
        lines.append(f"📊 Prob. Modelo: {prob_pct:.1f}% (Cuota justa: {fair_odd:.2f})")
        lines.append(f"💰 Cuota Real: {row['observed_odd']} | 📈 Valor (EV): +{ev_pct:.1f}%")
        lines.append(f"🔒 Confianza: {row['confidence_level']}")
        lines.append("-" * 35)

    full_msg = "\n".join(lines)
    res = TelegramReporterAgent.send_telegram_message(full_msg)

    if res.get("sent"):
        with get_db_connection() as conn:
            for row in opps:
                conn.execute("""
                INSERT OR IGNORE INTO prematch_sent_alerts (match_id, market, selection, sent_at_utc)
                VALUES (?, ?, ?, ?);
                """, (row["match_id"], row["market"], row["selection"], now_str))
        logger.info(f"Se han enviado {len(opps)} nuevas oportunidades a Telegram.")
    else:
        logger.warning(f"No se pudo enviar a Telegram: {res.get('reason')}")


if __name__ == "__main__":
    run_cloud_cycle()
