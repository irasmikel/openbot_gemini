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
    purge_synthetic_and_test_data,
    sync_standings_and_matches_football_data,
    sync_real_odds_from_the_odds_api,
    run_real_statistical_analysis
)

logger = get_logger("GitHubRunnerV4")
LOCAL_TZ = ZoneInfo("Europe/Madrid")


def parse_utc(utc_str: str) -> datetime:
    clean = utc_str.strip().replace("T", " ").replace("Z", "")[:19]
    return datetime.strptime(clean, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def format_kickoff_local(utc_str: str) -> str:
    try:
        dt_loc = parse_utc(utc_str).astimezone(LOCAL_TZ)
        return dt_loc.strftime("HOY a las %H:%M") + "h"
    except Exception:
        return utc_str[:16]


def build_clear_offer_phrase(selection: str, home_team: str, away_team: str) -> str:
    """Traduce el codigo tecnico a una frase 100% clara de que apostar en Bwin."""
    mapping = {
        "HOME": f"👉 GANA {home_team.upper()} (Victoria Local - 1)",
        "AWAY": f"👉 GANA {away_team.upper()} (Victoria Visitante - 2)",
        "DRAW": "👉 EMPATE (X)",
        "OVER_2.5": "👉 MAS DE 2.5 GOLES EN EL PARTIDO (3 o mas goles en total)",
        "UNDER_2.5": "👉 MENOS DE 2.5 GOLES EN EL PARTIDO (0, 1 o 2 goles en total)"
    }
    return mapping.get(selection, f"👉 {selection}")


def ensure_tracking_tables() -> None:
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
        conn.execute("""
        CREATE TABLE IF NOT EXISTS live_sent_alerts (
            match_id INTEGER NOT NULL,
            scenario_code TEXT NOT NULL,
            sent_at_utc TEXT NOT NULL,
            PRIMARY KEY (match_id, scenario_code)
        );
        """)


def check_and_send_prematch_alerts() -> None:
    """
    1. AVISOS ANTES DEL PARTIDO:
    Solo avisa cuando faltan MENOS DE 3 HORAS (180 minutos) para que empiece el partido,
    nunca con dias de antelacion. Mensaje en espanol claro y directo para Bwin.
    """
    now_utc = datetime.now(timezone.utc)
    now_str = now_utc.strftime("%Y-%m-%d %H:%M:%S")

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
        ORDER BY m.kickoff_utc ASC;
        """).fetchall()

    upcoming_opps = []
    for row in opps:
        try:
            dt_kick = parse_utc(row["kickoff_utc"])
            mins_to_kickoff = (dt_kick - now_utc).total_seconds() / 60.0
            # Solo partidos que empiezan entre dentro de 5 minutos y dentro de 180 minutos (3 horas)
            if 5.0 <= mins_to_kickoff <= 180.0:
                upcoming_opps.append((row, int(mins_to_kickoff)))
        except Exception:
            continue

    if not upcoming_opps:
        logger.info("No hay oportunidades previas que comiencen en las proximas 3 horas.")
        return

    for row, mins_left in upcoming_opps:
        hora_txt = format_kickoff_local(row["kickoff_utc"])
        propuesta_clara = build_clear_offer_phrase(row["selection"], row["local"], row["visitante"])
        prob_pct = float(row["estimated_prob"]) * 100.0
        cuota_minima = round(1.0 / float(row["estimated_prob"]), 2)
        cuota_bwin = float(row["observed_odd"])

        msg_lines = [
            "🟢 AVISO ANTES DEL PARTIDO (BWIN)",
            "",
            f"⚽ Partido: {row['local']} vs {row['visitante']}",
            f"🏆 Liga: {row['liga']}",
            f"🕒 Empieza: {hora_txt} (faltan {mins_left} min)",
            "",
            "🎯 ¿QUE TE PROPONE EL SISTEMA?",
            f"{propuesta_clara}",
            "",
            "💰 DATOS PARA BWIN:",
            f"• Cuota actual en Bwin: {cuota_bwin}",
            f"• Solo merece la pena si en Bwin se paga a mas de: {cuota_minima}",
            f"• Probabilidad calculada de acierto: {prob_pct:.0f}%",
            "",
            "💡 ¿POR QUE ES INTERESANTE?",
            f"{row['reasoning_json']}"
        ]

        res = TelegramReporterAgent.send_telegram_message("\n".join(msg_lines))
        if res.get("sent"):
            with get_db_connection() as conn:
                conn.execute("""
                INSERT OR IGNORE INTO prematch_sent_alerts (match_id, market, selection, sent_at_utc)
                VALUES (?, ?, ?, ?);
                """, (row["match_id"], row["market"], row["selection"], now_str))
            logger.info(f"Alerta previa enviada para {row['local']} vs {row['visitante']}.")


def check_and_send_live_alerts() -> None:
    """
    2. AVISOS EN DIRECTO (DURANTE EL PARTIDO):
    Detecta situaciones especiales mientras se juega el partido (por ejemplo,
    el favorito antes del partido va perdiendo o empatando pero su cuota en Bwin ha subido)
    y manda un aviso claro en lenguaje natural.
    """
    now_utc = datetime.now(timezone.utc)
    now_str = now_utc.strftime("%Y-%m-%d %H:%M:%S")

    with get_db_connection() as conn:
        live_matches = conn.execute("""
        SELECT m.match_id, c.name as liga, t1.canonical_name as local, t2.canonical_name as visitante,
               m.kickoff_utc, m.home_score, m.away_score,
               s1.position as h_pos, s1.points as h_pts,
               s2.position as a_pos, s2.points as a_pts,
               p.selection as pre_sel, p.estimated_prob as pre_prob, p.observed_odd as pre_odd
        FROM matches m
        JOIN competitions c ON m.competition_code = c.canonical_code
        JOIN teams t1 ON m.home_team_id = t1.team_id
        JOIN teams t2 ON m.away_team_id = t2.team_id
        LEFT JOIN team_season_stats s1 ON m.home_team_id = s1.team_id
        LEFT JOIN team_season_stats s2 ON m.away_team_id = s2.team_id
        LEFT JOIN predictions_audit p ON m.match_id = p.match_id
        WHERE m.status = 'LIVE';
        """).fetchall()

    if not live_matches:
        logger.info("No hay partidos en directo en este instante.")
        return

    for m in live_matches:
        m_id = int(m["match_id"])
        h_sc = int(m["home_score"] or 0)
        a_sc = int(m["away_score"] or 0)

        try:
            dt_kick = parse_utc(m["kickoff_utc"])
            elapsed_mins = int(max(1, min(90, (now_utc - dt_kick).total_seconds() / 60.0)))
            if elapsed_mins > 48:
                approx_min = max(46, elapsed_mins - 15)
            else:
                approx_min = elapsed_mins
        except Exception:
            approx_min = 45

        scenario_code = None
        what_happened = ""
        what_to_look = ""
        min_odd_bwin = 1.65

        # Caso 1: El equipo local era claro favorito antes de empezar y va perdiendo en casa entre el min 20 y 70
        if m["pre_sel"] == "HOME" and float(m["pre_prob"] or 0) >= 0.53 and h_sc < a_sc and (a_sc - h_sc) == 1 and 20 <= approx_min <= 70:
            scenario_code = "LIVE_FAV_HOME_TRAILING"
            what_happened = f"Sorpresa en el marcador: {m['local']} era claro favorito antes de empezar, pero va perdiendo {h_sc}-{a_sc} en casa."
            what_to_look = f"👉 {m['local']} REMONTARA O EMPATARA (Doble oportunidad 1X) o 👉 MAS DE {h_sc + a_sc + 0.5} GOLES"
            min_odd_bwin = 1.60

        # Caso 2: Partido entre equipos goleadores que sigue 0-0 en torno al descanso (min 30 a 60)
        elif h_sc == 0 and a_sc == 0 and 30 <= approx_min <= 62 and float(m["pre_prob"] or 0) >= 0.50:
            scenario_code = "LIVE_0_0_GOALS_WATCH"
            what_happened = f"El partido sigue 0-0 cerca del minuto {approx_min} pese a que habia clara tendencia ofensiva antes del inicio."
            what_to_look = "👉 HABRA AL MENOS 1 GOL EN EL PARTIDO (Mas de 0.5 goles) o 👉 MAS DE 1.5 GOLES"
            min_odd_bwin = 1.50

        if not scenario_code:
            continue

        with get_db_connection() as conn:
            already = conn.execute(
                "SELECT 1 FROM live_sent_alerts WHERE match_id = ? AND scenario_code = ?;",
                (m_id, scenario_code)
            ).fetchone()
        if already:
            continue

        msg_live = [
            "🔴 AVISO EN DIRECTO (PARTIDO EN JUEGO)",
            "",
            f"⚽ Partido: {m['local']} {h_sc} - {a_sc} {m['visitante']}",
            f"🏆 Liga: {m['liga']} | ⏱️ Minuto aprox.: {approx_min}'",
            "",
            "⚡ ¿QUE ESTA PASANDO?",
            f"{what_happened}",
            "",
            "🎯 ¿QUE TE PROPONE MIRAR EN BWIN AHORA?",
            f"{what_to_look}",
            "",
            "💰 REGLA DE SEGURIDAD:",
            f"• Abre Bwin, mira las estadisticas en vivo (tiros a puerta/rojas) y entra solo si la cuota supera {min_odd_bwin:.2f}."
        ]

        res = TelegramReporterAgent.send_telegram_message("\n".join(msg_live))
        if res.get("sent"):
            with get_db_connection() as conn:
                conn.execute("""
                INSERT OR IGNORE INTO live_sent_alerts (match_id, scenario_code, sent_at_utc)
                VALUES (?, ?, ?);
                """, (m_id, scenario_code, now_str))
            logger.info(f"Alerta en directo enviada para {m['local']} vs {m['visitante']}.")


def run_cloud_cycle() -> None:
    logger.info("=== INICIANDO CICLO AUTONOMO V4 (BWIN + PREPARTIDO <3H + DIRECTO) ===")
    init_database()
    ensure_standings_table()
    ensure_tracking_tables()
    purge_synthetic_and_test_data()

    sync_standings_and_matches_football_data()
    sync_real_odds_from_the_odds_api()
    run_real_statistical_analysis()

    check_and_send_prematch_alerts()
    check_and_send_live_alerts()


if __name__ == "__main__":
    run_cloud_cycle()
