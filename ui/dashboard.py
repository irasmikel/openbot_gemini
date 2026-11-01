import sys
import time
from pathlib import Path
from datetime import datetime, timedelta, timezone
import httpx

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.config import settings
from core.logger import get_logger
from core.database import init_database, get_db_connection, record_agent_heartbeat
from agents.quantstats import QuantStatsAgent

logger = get_logger("RealDataSyncV3")


def log_api_call(provider: str, endpoint: str, status_code: int) -> None:
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    with get_db_connection() as conn:
        conn.execute("""
        INSERT INTO api_usage_log (provider, endpoint, status_code, called_date_utc, called_timestamp_utc)
        VALUES (?, ?, ?, ?, ?);
        """, (provider, endpoint, status_code, today_str, now_str))


def purge_synthetic_and_test_data() -> None:
    logger.info("Limpiando datos de prueba y registros sinteticos anteriores...")
    with get_db_connection() as conn:
        conn.execute("DELETE FROM live_alerts;")
        conn.execute("DELETE FROM predictions_audit;")
        conn.execute("DELETE FROM odds_snapshots;")
        conn.execute("DELETE FROM matches WHERE football_data_match_id IS NULL OR football_data_match_id < 10000;")


def ensure_standings_table() -> None:
    with get_db_connection() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS team_season_stats (
            team_id INTEGER PRIMARY KEY,
            competition_code TEXT NOT NULL,
            position INTEGER NOT NULL,
            played_games INTEGER NOT NULL,
            won INTEGER NOT NULL,
            draw INTEGER NOT NULL,
            lost INTEGER NOT NULL,
            points INTEGER NOT NULL,
            goals_for INTEGER NOT NULL,
            goals_against INTEGER NOT NULL,
            updated_at_utc TEXT NOT NULL,
            FOREIGN KEY (team_id) REFERENCES teams(team_id)
        );
        """)


def normalize_team_key(name: str) -> str:
    if not name:
        return ""
    s = name.lower().strip()
    for token in ["fc", "cf", "ud", "rcd", "cd", "ssc", "ac", "as", "rb", "vfl", "1.", "sv", "bsc", "tsg", "sc", "osc", "rc", "afc", "de futbol", "de bilbao", "balompie", "club"]:
        s = s.replace(f" {token} ", " ").replace(f"^{token} ", "").replace(f" {token}$", "")
    replacements = {
        "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ü": "u", "ñ": "n", "ö": "o", "ä": "a",
        "athletic": "athletic bilbao",
        "real sociedad": "real sociedad",
        "atletico": "atletico madrid",
        "celta": "celta vigo",
        "betis": "real betis",
        "alaves": "alaves",
        "espanyol": "espanyol",
        "barcelona": "barcelona",
        "real madrid": "real madrid",
        "manchester united": "man united",
        "manchester city": "man city",
        "tottenham": "tottenham",
        "newcastle": "newcastle",
        "wolverhampton": "wolves",
        "nottingham": "nottingham",
        "brighton": "brighton",
        "west ham": "west ham",
        "aston villa": "aston villa",
        "bournemouth": "bournemouth",
        "inter": "inter milan",
        "milan": "ac milan",
        "napoli": "napoli",
        "juventus": "juventus",
        "atalanta": "atalanta",
        "bologna": "bologna",
        "fiorentina": "fiorentina",
        "lazio": "lazio",
        "roma": "roma",
        "bayern": "bayern munich",
        "leverkusen": "bayer leverkusen",
        "dortmund": "borussia dortmund",
        "leipzig": "rb leipzig",
        "frankfurt": "eintracht frankfurt",
        "stuttgart": "stuttgart",
        "m'gladbach": "monchengladbach",
        "monchengladbach": "monchengladbach",
        "paris": "paris saint germain",
        "psg": "paris saint germain",
        "marseille": "marseille",
        "monaco": "monaco",
        "lille": "lille",
        "lyon": "lyon",
    }
    for k, v in replacements.items():
        if k in s:
            s = s.replace(k, v)
    return "".join(ch for ch in s if ch.isalnum())


def teams_match(name_a: str, name_b: str) -> bool:
    ka = normalize_team_key(name_a)
    kb = normalize_team_key(name_b)
    if not ka or not kb:
        return False
    return ka == kb or ka in kb or kb in ka or ka[:6] == kb[:6]


def get_or_create_team(conn, team_name: str, comp_code: str, fd_team_id: int = None) -> int:
    if fd_team_id:
        row = conn.execute("SELECT team_id FROM teams WHERE football_data_team_id = ?;", (fd_team_id,)).fetchone()
        if row:
            conn.execute("UPDATE teams SET canonical_name = ? WHERE team_id = ?;", (team_name, row["team_id"]))
            return int(row["team_id"])

    row = conn.execute("SELECT team_id FROM teams WHERE canonical_name = ?;", (team_name,)).fetchone()
    if row:
        return int(row["team_id"])

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("""
    INSERT INTO teams (canonical_name, competition_code, football_data_team_id, elo_rating, updated_at_utc)
    VALUES (?, ?, ?, 1550.0, ?);
    """, (team_name, comp_code, fd_team_id, now_str))
    return int(conn.execute("SELECT last_insert_rowid() as id;").fetchone()["id"])


def sync_standings_and_matches_football_data() -> int:
    if not settings.is_key_configured(settings.football_data_api_key):
        return 0

    token = settings.football_data_api_key.get_secret_value().strip()
    headers = {"X-Auth-Token": token}

    date_from = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    date_to = (datetime.now(timezone.utc) + timedelta(days=4)).strftime("%Y-%m-%d")

    with get_db_connection() as conn:
        comps = conn.execute("SELECT canonical_code, football_data_code, name FROM competitions WHERE is_active = 1;").fetchall()

    total_matches = 0
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    with httpx.Client(timeout=15.0) as client:
        for comp in comps:
            fd_code = comp["football_data_code"]
            if not fd_code:
                continue

            st_url = f"https://api.football-data.org/v4/competitions/{fd_code}/standings"
            try:
                r_st = client.get(st_url, headers=headers)
                log_api_call("FOOTBALL_DATA", f"/competitions/{fd_code}/standings", r_st.status_code)
                if r_st.status_code == 200:
                    st_data = r_st.json()
                    for st_block in st_data.get("standings", []):
                        if st_block.get("type") == "TOTAL":
                            with get_db_connection() as conn:
                                for row_t in st_block.get("table", []):
                                    t_info = row_t.get("team", {})
                                    t_name = t_info.get("shortName") or t_info.get("name")
                                    if not t_name:
                                        continue
                                    t_id = get_or_create_team(conn, t_name, comp["canonical_code"], t_info.get("id"))
                                    played = max(1, int(row_t.get("playedGames", 1)))
                                    pts = int(row_t.get("points", 0))
                                    gf = int(row_t.get("goalsFor", 0))
                                    ga = int(row_t.get("goalsAgainst", 0))
                                    pos = int(row_t.get("position", 10))
                                    elo_est = 1500.0 + ((pts / played) - 1.35) * 180.0 + ((gf - ga) / played) * 45.0

                                    conn.execute("UPDATE teams SET elo_rating = ?, updated_at_utc = ? WHERE team_id = ?;", (round(elo_est, 1), now_str, t_id))
                                    conn.execute("""
                                    INSERT INTO team_season_stats (
                                        team_id, competition_code, position, played_games, won, draw, lost, points, goals_for, goals_against, updated_at_utc
                                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                    ON CONFLICT(team_id) DO UPDATE SET
                                        position = excluded.position,
                                        played_games = excluded.played_games,
                                        won = excluded.won,
                                        draw = excluded.draw,
                                        lost = excluded.lost,
                                        points = excluded.points,
                                        goals_for = excluded.goals_for,
                                        goals_against = excluded.goals_against,
                                        updated_at_utc = excluded.updated_at_utc;
                                    """, (
                                        t_id, comp["canonical_code"], pos, played,
                                        int(row_t.get("won", 0)), int(row_t.get("draw", 0)), int(row_t.get("lost", 0)),
                                        pts, gf, ga, now_str
                                    ))
                time.sleep(0.35)
            except Exception as e:
                logger.error(f"Error descargando clasificacion de {comp['name']}: {e}")

            m_url = f"https://api.football-data.org/v4/competitions/{fd_code}/matches"
            try:
                r_m = client.get(m_url, headers=headers, params={"dateFrom": date_from, "dateTo": date_to})
                log_api_call("FOOTBALL_DATA", f"/competitions/{fd_code}/matches", r_m.status_code)
                if r_m.status_code == 200:
                    matches_list = r_m.json().get("matches", [])
                    with get_db_connection() as conn:
                        for m in matches_list:
                            fd_match_id = m.get("id")
                            h_info = m.get("homeTeam", {})
                            a_info = m.get("awayTeam", {})
                            h_name = h_info.get("shortName") or h_info.get("name")
                            a_name = a_info.get("shortName") or a_info.get("name")
                            if not h_name or not a_name:
                                continue

                            h_id = get_or_create_team(conn, h_name, comp["canonical_code"], h_info.get("id"))
                            a_id = get_or_create_team(conn, a_name, comp["canonical_code"], a_info.get("id"))

                            utc_date = (m.get("utcDate") or "").replace("T", " ").replace("Z", "")[:19]
                            raw_status = m.get("status", "SCHEDULED")
                            if raw_status in ("IN_PLAY", "PAUSED"):
                                st_mapped = "LIVE"
                            elif raw_status == "FINISHED":
                                st_mapped = "FINISHED"
                            else:
                                st_mapped = "SCHEDULED"

                            score_ft = m.get("score", {}).get("fullTime", {})
                            h_score = score_ft.get("home")
                            a_score = score_ft.get("away")

                            conn.execute("""
                            INSERT INTO matches (
                                competition_code, home_team_id, away_team_id, kickoff_utc,
                                status, home_score, away_score, football_data_match_id, last_updated_utc
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(football_data_match_id) DO UPDATE SET
                                home_team_id = excluded.home_team_id,
                                away_team_id = excluded.away_team_id,
                                kickoff_utc = excluded.kickoff_utc,
                                status = excluded.status,
                                home_score = excluded.home_score,
                                away_score = excluded.away_score,
                                last_updated_utc = excluded.last_updated_utc;
                            """, (
                                comp["canonical_code"], h_id, a_id, utc_date,
                                st_mapped, h_score, a_score, fd_match_id, now_str
                            ))
                            total_matches += 1
                time.sleep(0.35)
            except Exception as e:
                logger.error(f"Error descargando partidos de {comp['name']}: {e}")

    return total_matches


def sync_real_odds_from_the_odds_api() -> int:
    if not settings.is_key_configured(settings.odds_api_key):
        return 0

    api_key = settings.odds_api_key.get_secret_value().strip()
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    matched_odds_count = 0

    with get_db_connection() as conn:
        comps = conn.execute("SELECT canonical_code, odds_api_key, name FROM competitions WHERE is_active = 1;").fetchall()
        db_matches = conn.execute("""
        SELECT m.match_id, m.competition_code, t1.canonical_name as home_name, t2.canonical_name as away_name
        FROM matches m
        JOIN teams t1 ON m.home_team_id = t1.team_id
        JOIN teams t2 ON m.away_team_id = t2.team_id
        WHERE m.status IN ('SCHEDULED', 'LIVE');
        """).fetchall()

    with httpx.Client(timeout=15.0) as client:
        for comp in comps:
            sport_key = comp["odds_api_key"]
            if not sport_key:
                continue

            comp_matches = [m for m in db_matches if m["competition_code"] == comp["canonical_code"]]
            if not comp_matches:
                continue

            url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/"
            params = {
                "apiKey": api_key,
                "regions": "eu",
                "markets": "h2h",
                "oddsFormat": "decimal"
            }

            try:
                resp = client.get(url, params=params)
                log_api_call("ODDS_API", f"/sports/{sport_key}/odds", resp.status_code)
                if resp.status_code != 200:
                    continue

                events = resp.json()
                for ev in events:
                    ev_home = ev.get("home_team", "")
                    ev_away = ev.get("away_team", "")
                    bookmakers = ev.get("bookmakers", [])
                    if not bookmakers:
                        continue

                    target_match = None
                    for db_m in comp_matches:
                        if teams_match(db_m["home_name"], ev_home) and teams_match(db_m["away_name"], ev_away):
                            target_match = db_m
                            break

                    if not target_match:
                        continue

                    odd_h_list, odd_x_list, odd_a_list = [], [], []
                    bookie_names = []
                    for bm in bookmakers:
                        bm_title = bm.get("title", "EU Bookie")
                        for mk in bm.get("markets", []):
                            if mk.get("key") == "h2h":
                                outcomes = mk.get("outcomes", [])
                                o_h, o_x, o_a = None, None, None
                                for out in outcomes:
                                    if out.get("name") == ev_home:
                                        o_h = float(out.get("price", 0))
                                    elif out.get("name") == ev_away:
                                        o_a = float(out.get("price", 0))
                                    elif out.get("name", "").lower() == "draw":
                                        o_x = float(out.get("price", 0))
                                if o_h and o_x and o_a:
                                    odd_h_list.append(o_h)
                                    odd_x_list.append(o_x)
                                    odd_a_list.append(o_a)
                                    bookie_names.append(bm_title)

                    if not odd_h_list:
                        continue

                    avg_h = round(sum(odd_h_list) / len(odd_h_list), 2)
                    avg_x = round(sum(odd_x_list) / len(odd_x_list), 2)
                    avg_a = round(sum(odd_a_list) / len(odd_a_list), 2)

                    raw_h = 1.0 / avg_h
                    raw_x = 1.0 / avg_x
                    raw_a = 1.0 / avg_a
                    overround = (raw_h + raw_x + raw_a) - 1.0
                    total_raw = raw_h + raw_x + raw_a

                    m_id = int(target_match["match_id"])
                    bm_label = f"Media {len(odd_h_list)} Casas EU ({bookie_names[0]})"

                    with get_db_connection() as conn:
                        conn.execute("DELETE FROM odds_snapshots WHERE match_id = ? AND market = '1X2';", (m_id,))
                        for sel, odd_v, r_p in [("HOME", avg_h, raw_h), ("DRAW", avg_x, raw_x), ("AWAY", avg_a, raw_a)]:
                            conn.execute("""
                            INSERT INTO odds_snapshots (
                                match_id, bookmaker, market, selection, odd_value,
                                implied_prob_raw, implied_prob_fair, market_margin, captured_at_utc
                            ) VALUES (?, ?, '1X2', ?, ?, ?, ?, ?, ?);
                            """, (
                                m_id, bm_label, sel, odd_v,
                                round(r_p, 4), round(r_p / total_raw, 4), round(overround, 4), now_str
                            ))
                    matched_odds_count += 1
            except Exception as e:
                logger.error(f"Error consultando The Odds API para {comp['name']}: {e}")

    return matched_odds_count


def run_real_statistical_analysis() -> None:
    record_agent_heartbeat("AGENT_02_QUANTSTATS", status="RUNNING")
    record_agent_heartbeat("AGENT_03_MARKETODDS", status="RUNNING")
    record_agent_heartbeat("AGENT_06_PREMATCH_OPP", status="RUNNING")

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    with get_db_connection() as conn:
        matches = conn.execute("""
        SELECT m.match_id, m.competition_code, m.home_team_id, m.away_team_id,
               t1.canonical_name as home_name, t2.canonical_name as away_name,
               s1.position as h_pos, s1.played_games as h_pj, s1.points as h_pts, s1.goals_for as h_gf, s1.goals_against as h_ga,
               s2.position as a_pos, s2.played_games as a_pj, s2.points as a_pts, s2.goals_for as a_gf, s2.goals_against as a_ga
        FROM matches m
        JOIN teams t1 ON m.home_team_id = t1.team_id
        JOIN teams t2 ON m.away_team_id = t2.team_id
        LEFT JOIN team_season_stats s1 ON m.home_team_id = s1.team_id
        LEFT JOIN team_season_stats s2 ON m.away_team_id = s2.team_id
        ORDER BY m.kickoff_utc ASC;
        """).fetchall()

        for m in matches:
            m_id = int(m["match_id"])

            if m["h_pj"] and m["a_pj"] and int(m["h_pj"]) > 0 and int(m["a_pj"]) > 0:
                h_gf_pg = float(m["h_gf"]) / float(m["h_pj"])
                h_ga_pg = float(m["h_ga"]) / float(m["h_pj"])
                a_gf_pg = float(m["a_gf"]) / float(m["a_pj"])
                a_ga_pg = float(m["a_ga"]) / float(m["a_pj"])

                lambda_h = round(max(0.45, min(3.40, ((h_gf_pg + a_ga_pg) / 2.0) * 1.12)), 2)
                lambda_a = round(max(0.35, min(3.10, ((a_gf_pg + h_ga_pg) / 2.0) * 0.90)), 2)
                stats_note = (
                    f"{m['home_name']} ({m['h_pos']}o, {m['h_pts']} pts, {m['h_gf']} GF / {m['h_ga']} GC en {m['h_pj']} PJ) vs "
                    f"{m['away_name']} ({m['a_pos']}o, {m['a_pts']} pts, {m['a_gf']} GF / {m['a_ga']} GC en {m['a_pj']} PJ). "
                    f"Goles esperados Poisson: Local {lambda_h} - Visitante {lambda_a}."
                )
                has_real_standings = True
            else:
                lambda_h = 1.48
                lambda_a = 1.18
                stats_note = f"Fase europea / Sin tabla domestica cruzada. Lambda base: {lambda_h} vs {lambda_a}."
                has_real_standings = False

            probs = QuantStatsAgent.calculate_match_probabilities(lambda_h, lambda_a)

            odds_rows = conn.execute(
                "SELECT selection, odd_value, implied_prob_fair, bookmaker FROM odds_snapshots WHERE match_id = ? AND market = '1X2';",
                (m_id,)
            ).fetchall()
            odds_map = {r["selection"]: r for r in odds_rows}

            candidates = [
                ("HOME", f"Victoria {m['home_name']} (1)", float(probs["p_home"])),
                ("DRAW", "Empate (X)", float(probs["p_draw"])),
                ("AWAY", f"Victoria {m['away_name']} (2)", float(probs["p_away"])),
            ]

            best_eval = None
            for sel_code, sel_label, p_est in candidates:
                if sel_code in odds_map:
                    odd_val = float(odds_map[sel_code]["odd_value"])
                    fair_mkt = float(odds_map[sel_code]["implied_prob_fair"])
                    ev = (p_est * odd_val) - 1.0
                else:
                    odd_val = None
                    fair_mkt = None
                    ev = None

                item = {
                    "sel_code": sel_code,
                    "sel_label": sel_label,
                    "p_est": p_est,
                    "odd_val": odd_val,
                    "fair_mkt": fair_mkt,
                    "ev": ev
                }
                if best_eval is None:
                    best_eval = item
                else:
                    if item["ev"] is not None and (best_eval["ev"] is None or item["ev"] > best_eval["ev"]):
                        best_eval = item
                    elif item["ev"] is None and best_eval["ev"] is None and item["p_est"] > best_eval["p_est"]:
                        best_eval = item

            if best_eval["odd_val"] is None:
                decision = "SIN_CUOTAS_VERIFICADAS"
                confidence = "MEDIA" if has_real_standings else "BAJA"
                reason_text = f"{stats_note} | Favorito estadistico: {best_eval['sel_label']} ({best_eval['p_est']*100:.1f}%). Cuotas aun no abiertas o no vinculadas en The Odds API."
            else:
                ev_val = best_eval["ev"]
                if ev_val >= 0.04 and best_eval["p_est"] >= 0.38 and has_real_standings:
                    decision = "OPORTUNIDAD"
                    confidence = "ALTA" if ev_val >= 0.08 else "MEDIA"
                    reason_text = f"{stats_note} | Discrepancia detectada en {best_eval['sel_label']}: Modelo estima {best_eval['p_est']*100:.1f}% (Cuota justa {1.0/best_eval['p_est']:.2f}) frente a cuota real {best_eval['odd_val']}."
                elif ev_val >= 0.015:
                    decision = "VIGILAR"
                    confidence = "MEDIA"
                    reason_text = f"{stats_note} | Ligero valor en {best_eval['sel_label']} (EV +{ev_val*100:.1f}%), pero margen insuficiente para entrar pre-partido."
                else:
                    decision = "NO_APOSTAR"
                    confidence = "ALTA"
                    reason_text = f"{stats_note} | Cuotas eficientes. Mejor opcion ({best_eval['sel_label']} a {best_eval['odd_val']}) tiene EV {ev_val*100:+.1f}%. Mercado bien ajustado por las casas."

            conn.execute("DELETE FROM predictions_audit WHERE match_id = ? AND stage = 'PREMATCH';", (m_id,))
            conn.execute("""
            INSERT INTO predictions_audit (
                match_id, stage, market, selection, estimated_prob, observed_odd,
                fair_prob_market, expected_value, confidence_level, decision, reasoning_json, created_at_utc
            ) VALUES (?, 'PREMATCH', '1X2', ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                m_id,
                best_eval["sel_code"],
                round(best_eval["p_est"], 4),
                best_eval["odd_val"],
                best_eval["fair_mkt"],
                round(best_eval["ev"], 4) if best_eval["ev"] is not None else None,
                confidence,
                decision,
                reason_text,
                now_str
            ))

    for code in ["AGENT_01_ORCHESTRATOR", "AGENT_02_QUANTSTATS", "AGENT_03_MARKETODDS", "AGENT_04_05_CONTEXT", "AGENT_06_PREMATCH_OPP", "AGENT_09_DATAGUARD"]:
        record_agent_heartbeat(code, status="IDLE")


def _run_cli_sync():
    init_database()
    ensure_standings_table()
    purge_synthetic_and_test_data()
    sync_standings_and_matches_football_data()
    sync_real_odds_from_the_odds_api()
    run_real_statistical_analysis()


import sys
from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import pandas as pd
import streamlit as st

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from core.config import settings
from core.database import init_database, get_db_connection, get_daily_api_calls
from agents.quantstats import QuantStatsAgent
from agents.marketodds import MarketOddsAgent
from agents.auditor import AuditorAgent
from agents.telegram_reporter import TelegramReporterAgent
# Funciones de sincronizacion integradas directamente para evitar ImportError

st.set_page_config(
    page_title="Football Intelligence V3 | Centro de Decision Deportiva",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded"
)

init_database()
ensure_standings_table()

LOCAL_TZ = ZoneInfo("Europe/Madrid")
DIAS_ES = ["Lun", "Mar", "Mie", "Jue", "Vie", "Sab", "Dom"]


def format_kickoff_madrid(utc_str: str) -> str:
    """Convierte la fecha UTC de la API a la hora exacta de Madrid/Euskadi (CET)."""
    if not utc_str:
        return "Hora pendiente"
    try:
        clean = utc_str.strip().replace("T", " ").replace("Z", "")[:19]
        dt_utc = datetime.strptime(clean, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        dt_loc = dt_utc.astimezone(LOCAL_TZ)
        now_loc = datetime.now(LOCAL_TZ)

        if dt_loc.date() == now_loc.date():
            day_prefix = "HOY"
        elif (dt_loc.date() - now_loc.date()).days == 1:
            day_prefix = "MANANA"
        elif (dt_loc.date() - now_loc.date()).days == -1:
            day_prefix = "AYER"
        else:
            day_prefix = f"{DIAS_ES[dt_loc.weekday()]} {dt_loc.strftime('%d/%m')}"

        return f"{day_prefix} · {dt_loc.strftime('%H:%M')}h"
    except Exception:
        return utc_str[:16]


def is_match_today_madrid(utc_str: str) -> bool:
    if not utc_str:
        return False
    try:
        clean = utc_str.strip().replace("T", " ").replace("Z", "")[:19]
        dt_utc = datetime.strptime(clean, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        return dt_utc.astimezone(LOCAL_TZ).date() == datetime.now(LOCAL_TZ).date()
    except Exception:
        return False


def translate_selection(sel: str, home_team: str, away_team: str) -> str:
    if sel == "HOME":
        return f"Gana {home_team} (Local - 1)"
    if sel == "AWAY":
        return f"Gana {away_team} (Visitante - 2)"
    if sel == "DRAW":
        return "Empate (X)"
    return sel


def load_query_df(query: str, params: tuple = ()) -> pd.DataFrame:
    with get_db_connection() as conn:
        return pd.read_sql_query(query, conn, params=params)


# Si quedan restos de los partidos de prueba (football_data_match_id < 10000 o NULL), limpiar y sincronizar
df_dirty = load_query_df("SELECT COUNT(*) as c FROM matches WHERE football_data_match_id IS NULL OR football_data_match_id < 10000;")
if not df_dirty.empty and int(df_dirty.iloc[0]["c"]) > 0:
    with st.spinner("Purificando base de datos (eliminando datos de prueba) y descargando jornada real de las APIs..."):
        purge_synthetic_and_test_data()
        sync_standings_and_matches_football_data()
        sync_real_odds_from_the_odds_api()
        run_real_statistical_analysis()

# Estilos CSS de alta legibilidad sin recortes superiores
st.markdown("""
<style>
    .block-container {
        padding-top: 2.2rem !important;
        padding-bottom: 2.5rem !important;
    }
    .stApp {
        background-color: #0b0f19;
        color: #f8fafc;
    }
    section[data-testid="stSidebar"] {
        background-color: #090d16 !important;
        border-right: 1px solid #1e293b;
    }
    .guide-banner {
        background: linear-gradient(90deg, #0f172a 0%, #1e293b 100%);
        border: 1px solid #334155;
        border-left: 5px solid #10b981;
        border-radius: 10px;
        padding: 14px 20px;
        margin-bottom: 18px;
    }
    .kpi-box {
        background: #111827;
        border: 1px solid #1f2937;
        border-top: 3px solid #10b981;
        border-radius: 10px;
        padding: 14px 16px;
    }
    .kpi-title {
        font-size: 0.76rem;
        color: #94a3b8;
        text-transform: uppercase;
        font-weight: 700;
        letter-spacing: 0.6px;
    }
    .kpi-num {
        font-size: 1.65rem;
        font-weight: 800;
        color: #ffffff;
        margin-top: 2px;
    }
    .kpi-desc {
        font-size: 0.78rem;
        color: #64748b;
        margin-top: 2px;
    }
    .decision-card {
        background: #111827;
        border: 1px solid #1e293b;
        border-radius: 12px;
        padding: 18px 22px;
        margin-bottom: 14px;
    }
    .pill-time {
        background: #1e293b;
        color: #38bdf8;
        border: 1px solid #334155;
        padding: 4px 11px;
        border-radius: 6px;
        font-size: 0.8rem;
        font-weight: 700;
    }
    .pill-opp {
        background: #064e3b;
        color: #34d399;
        border: 1px solid #10b981;
        padding: 4px 12px;
        border-radius: 6px;
        font-size: 0.8rem;
        font-weight: 700;
    }
    .pill-watch {
        background: #451a03;
        color: #fbbf24;
        border: 1px solid #f59e0b;
        padding: 4px 12px;
        border-radius: 6px;
        font-size: 0.8rem;
        font-weight: 700;
    }
    .pill-pass {
        background: #1f2937;
        color: #94a3b8;
        border: 1px solid #374151;
        padding: 4px 12px;
        border-radius: 6px;
        font-size: 0.8rem;
        font-weight: 600;
    }
    .action-box {
        background: #0f172a;
        border: 1px solid #1e293b;
        border-radius: 8px;
        padding: 10px 14px;
        margin-top: 10px;
        font-size: 0.9rem;
    }
</style>
""", unsafe_allow_html=True)


# Barra lateral
with st.sidebar:
    st.markdown("### ⚽ FOOTBALL INTELLIGENCE")
    st.caption("Datos 100% Reales · Horario Europe/Madrid")

    if st.button("🔄 ACTUALIZAR PARTIDOS Y CUOTAS REALES", use_container_width=True, type="primary"):
        with st.spinner("Sincronizando football-data.org y The Odds API..."):
            purge_synthetic_and_test_data()
            sync_standings_and_matches_football_data()
            sync_real_odds_from_the_odds_api()
            run_real_statistical_analysis()
        st.success("Datos reales actualizados.")
        st.rerun()

    st.markdown("---")
    menu = st.radio(
        "SECCIONES DEL PANEL",
        [
            "🎯 1. QUE MIRAR HOY (RESUMEN CLARO)",
            "📅 2. CALENDARIO REAL Y HORARIOS",
            "🧮 3. SIMULADOR Y ANALISIS PREVIO",
            "⚡ 4. MONITOR EN DIRECTO (LIVE)",
            "🤖 5. ESTADO DE LOS AGENTES",
            "📈 6. RENDIMIENTO Y BRIER SCORE",
            "⚙️ 7. CONFIGURACION Y TELEGRAM"
        ]
    )

    st.markdown("---")
    st.markdown("**Consumo de Cuota API (Hoy):**")
    st.caption(f"• Football-Data: **{get_daily_api_calls('FOOTBALL_DATA')}** llamadas")
    st.caption(f"• The Odds API: **{get_daily_api_calls('ODDS_API')} / {settings.max_daily_odds_api_calls}**")
    st.caption(f"• SportScore: **{get_daily_api_calls('SPORTSCORE')} / {settings.max_daily_sportscore_calls}**")
    st.caption(f"• Telegram: **{get_daily_api_calls('TELEGRAM')}** alertas")


# Consulta maestra de todos los partidos reales y su evaluacion
df_master = load_query_df("""
    SELECT m.match_id, c.name as Liga, m.competition_code,
           t1.canonical_name as Local, t2.canonical_name as Visitante,
           m.kickoff_utc, m.status, m.minute, m.home_score, m.away_score,
           s1.position as h_pos, s1.points as h_pts, s1.played_games as h_pj,
           s2.position as a_pos, s2.points as a_pts, s2.played_games as a_pj,
           p.market, p.selection, p.estimated_prob, p.observed_odd,
           p.fair_prob_market, p.expected_value, p.confidence_level,
           p.decision, p.reasoning_json
    FROM matches m
    JOIN competitions c ON m.competition_code = c.canonical_code
    JOIN teams t1 ON m.home_team_id = t1.team_id
    JOIN teams t2 ON m.away_team_id = t2.team_id
    LEFT JOIN team_season_stats s1 ON m.home_team_id = s1.team_id
    LEFT JOIN team_season_stats s2 ON m.away_team_id = s2.team_id
    LEFT JOIN predictions_audit p ON m.match_id = p.match_id
    ORDER BY m.kickoff_utc ASC;
""")

if not df_master.empty:
    df_master["Hora_Local"] = df_master["kickoff_utc"].apply(format_kickoff_madrid)
    df_master["Es_Hoy"] = df_master["kickoff_utc"].apply(is_match_today_madrid)


# ==============================================================================
# 1. QUE MIRAR HOY (PANEL INTUITIVO DE DECISION)
# ==============================================================================
if menu.startswith("🎯"):
    st.markdown("## 🎯 Centro de Decision: ¿Que partidos merecen tu atencion?")

    st.markdown("""
    <div class="guide-banner">
        <b>🧭 Guia rapida de lectura (3 pasos):</b><br>
        1️⃣ <b>Local siempre a la izquierda, Visitante a la derecha</b> y <b>hora exacta en horario de Espana (CET)</b>.<br>
        2️⃣ Fijate en la comparacion clave: si la <b>Cuota Real de la Casa</b> es mas alta que la <b>Cuota Minima Justa</b> calculada por nuestro modelo, existe ventaja matematica (<b>Valor Esperado EV+</b>).<br>
        3️⃣ Si un partido aparece como <b>NO APOSTAR</b>, significa que las casas de apuestas han ajustado bien la cuota y no hay ventaja.
    </div>
    """, unsafe_allow_html=True)

    if df_master.empty:
        st.warning("No hay partidos cargados. Pulsa el boton verde 'ACTUALIZAR PARTIDOS Y CUOTAS REALES' en la barra izquierda.")
    else:
        df_today = df_master[df_master["Es_Hoy"] == True]
        df_opps = df_master[df_master["decision"] == "OPORTUNIDAD"]
        df_watch = df_master[df_master["decision"] == "VIGILAR"]
        df_live = df_master[df_master["status"] == "LIVE"]

        k1, k2, k3, k4 = st.columns(4)
        k1.markdown(f'<div class="kpi-box"><div class="kpi-title">PARTIDOS REALES HOY</div><div class="kpi-num">{len(df_today)}</div><div class="kpi-desc">Total proximos 4 dias: {len(df_master)}</div></div>', unsafe_allow_html=True)
        k2.markdown(f'<div class="kpi-box" style="border-top-color:#34d399;"><div class="kpi-title">OPORTUNIDADES CON VALOR (EV+)</div><div class="kpi-num" style="color:#34d399;">{len(df_opps)}</div><div class="kpi-desc">Cuota Casa > Cuota Justa</div></div>', unsafe_allow_html=True)
        k3.markdown(f'<div class="kpi-box" style="border-top-color:#fbbf24;"><div class="kpi-title">PARA VIGILAR EN DIRECTO</div><div class="kpi-num" style="color:#fbbf24;">{len(df_watch)}</div><div class="kpi-desc">Valor ajustado pre-partido</div></div>', unsafe_allow_html=True)
        k4.markdown(f'<div class="kpi-box" style="border-top-color:#ef4444;"><div class="kpi-title">EN JUEGO AHORA MISMO</div><div class="kpi-num" style="color:#f87171;">{len(df_live)}</div><div class="kpi-desc">Supervisados por Agente 7</div></div>', unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        view_filter = st.radio(
            "Filtrar vista rapida:",
            ["📅 Solo Partidos de HOY", "✅ Solo Oportunidades y Vigilancia (EV+)", "🌍 Todos los Partidos de la Jornada"],
            horizontal=True
        )

        if view_filter.startswith("📅"):
            df_show = df_today if not df_today.empty else df_master
            if df_today.empty:
                st.info("No hay partidos adicionales hoy; mostrando los siguientes encuentros programados.")
        elif view_filter.startswith("✅"):
            df_show = df_master[df_master["decision"].isin(["OPORTUNIDAD", "VIGILAR"])]
        else:
            df_show = df_master

        if df_show.empty:
            st.info("Ningun partido cumple este filtro ahora mismo. Revisa la pestana 'Todos los Partidos de la Jornada'.")
        else:
            for _, row in df_show.iterrows():
                dec = row["decision"] or "SIN_ANALIZAR"
                if dec == "OPORTUNIDAD":
                    badge_dec = '<span class="pill-opp">✅ OPORTUNIDAD DETECTADA (CON VALOR)</span>'
                elif dec == "VIGILAR":
                    badge_dec = '<span class="pill-watch">👀 VIGILAR EVOLUCION / EN DIRECTO</span>'
                elif dec == "NO_APOSTAR":
                    badge_dec = '<span class="pill-pass">⛔ NO APOSTAR (CUOTA SIN VALOR)</span>'
                else:
                    badge_dec = '<span class="pill-pass">⏳ ANALISIS ESTADISTICO (ESPERANDO CUOTAS)</span>'

                h_rank = f"({int(row['h_pos'])}º · {int(row['h_pts'])} pts)" if pd.notna(row["h_pos"]) else ""
                a_rank = f"({int(row['a_pos'])}º · {int(row['a_pts'])} pts)" if pd.notna(row["a_pos"]) else ""

                sel_readable = translate_selection(str(row["selection"]), row["Local"], row["Visitante"])
                prob_pct = float(row["estimated_prob"] or 0.0) * 100.0
                fair_odd = round(1.0 / float(row["estimated_prob"]), 2) if row["estimated_prob"] else 0.0

                if pd.notna(row["observed_odd"]) and float(row["observed_odd"]) > 0:
                    odd_str = f"{float(row['observed_odd']):.2f}"
                    ev_pct = float(row["expected_value"] or 0.0) * 100.0
                    ev_str = f"{ev_pct:+.1f}%"
                    ev_color = "#34d399" if ev_pct >= 3.0 else ("#fbbf24" if ev_pct > 0 else "#f87171")
                else:
                    odd_str = "No disponible"
                    ev_str = "Pendiente cuota"
                    ev_color = "#94a3b8"

                score_badge = ""
                if row["status"] == "LIVE":
                    score_badge = f" · 🔴 EN DIRECTO: {int(row['home_score'] or 0)} - {int(row['away_score'] or 0)}"
                elif row["status"] == "FINISHED":
                    score_badge = f" · FINALIZADO: {int(row['home_score'] or 0)} - {int(row['away_score'] or 0)}"

                st.markdown(f"""
                <div class="decision-card">
                    <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
                        <div>
                            <span style="color:#94a3b8; font-weight:700; font-size:0.85rem;">🏆 {row['Liga']}</span>
                            <span class="pill-time" style="margin-left:10px;">🕒 {row['Hora_Local']}{score_badge}</span>
                        </div>
                        <div>{badge_dec}</div>
                    </div>
                    <div style="font-size:1.3rem; font-weight:800; color:#ffffff; margin:12px 0 8px 0;">
                        🏠 {row['Local']} <span style="font-size:0.88rem; color:#94a3b8; font-weight:500;">{h_rank}</span>
                        <span style="color:#fbbf24; margin:0 12px;">vs</span>
                        ✈️ {row['Visitante']} <span style="font-size:0.88rem; color:#94a3b8; font-weight:500;">{a_rank}</span>
                    </div>
                    <div class="action-box">
                        <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap:12px;">
                            <div>🎯 <b> Pronostico Principal:</b><br><span style="color:#38bdf8; font-weight:700;">{sel_readable}</span></div>
                            <div>📊 <b>Probabilidad Real (Modelo):</b><br><span style="color:#ffffff; font-weight:700;">{prob_pct:.1f}%</span></div>
                            <div>⚖️ <b>Cuota Minima Justa:</b><br><span style="color:#cbd5e1; font-weight:700;">{fair_odd:.2f}</span> <span style="font-size:0.75rem; color:#64748b;">(No entrar por debajo)</span></div>
                            <div>💰 <b>Cuota Real en Casas:</b><br><span style="color:#fbbf24; font-weight:800; font-size:1.05rem;">{odd_str}</span></div>
                            <div>📈 <b>Ventaja / Valor (EV):</b><br><span style="color:{ev_color}; font-weight:800;">{ev_str}</span></div>
                        </div>
                        <div style="margin-top:8px; padding-top:8px; border-top:1px solid #1e293b; font-size:0.83rem; color:#94a3b8;">
                            💡 <b>Explicacion del Agente:</b> {row['reasoning_json'] or 'Analisis estadistico completado.'}
                        </div>
                    </div>
                </div>
                """, unsafe_allow_html=True)


# ==============================================================================
# 2. CALENDARIO REAL Y HORARIOS
# ==============================================================================
elif menu.startswith("📅"):
    st.markdown("## 📅 Calendario Oficial de las 7 Competiciones Europeas")
    st.caption("Datos verificados directamente desde football-data.org con horario local (Europe/Madrid).")

    df_comps = load_query_df("SELECT canonical_code, name FROM competitions WHERE is_active = 1;")
    comp_sel = st.selectbox(
        "Filtrar por Competicion:",
        ["TODAS"] + [f"{r['canonical_code']} - {r['name']}" for _, r in df_comps.iterrows()]
    )

    df_cal = df_master.copy()
    if comp_sel != "TODAS":
        c_code = comp_sel.split(" - ")[0]
        df_cal = df_cal[df_cal["competition_code"] == c_code]

    if not df_cal.empty:
        display_df = pd.DataFrame({
            "Fecha y Hora (Espana)": df_cal["Hora_Local"],
            "Competicion": df_cal["Liga"],
            "Equipo Local (Casa)": df_cal["Local"],
            "Equipo Visitante (Fuera)": df_cal["Visitante"],
            "Estado": df_cal["status"],
            "Seleccion Mas Probable": [translate_selection(str(r["selection"]), r["Local"], r["Visitante"]) for _, r in df_cal.iterrows()],
            "Prob. Modelo": [f"{float(p or 0)*100:.1f}%" for p in df_cal["estimated_prob"]],
            "Cuota Min. Justa": [round(1.0 / float(p), 2) if p else None for p in df_cal["estimated_prob"]],
            "Cuota Real Casa": df_cal["observed_odd"],
            "Veredicto Agente 6": df_cal["decision"]
        })
        st.dataframe(display_df, use_container_width=True, hide_index=True)


# ==============================================================================
# 3. SIMULADOR Y ANALISIS PREVIO
# ==============================================================================
elif menu.startswith("🧮"):
    st.markdown("## 🧮 Calculadora Interactiva de Partido (Compara tu Casa de Apuestas)")
    st.caption("Introduce las cuotas que ves en tu casa de apuestas para cualquier partido y el Agente 3 te dira si tienen valor matematico.")

    if not df_master.empty:
        match_labels = [f"{r['Hora_Local']} | {r['Local']} vs {r['Visitante']} ({r['Liga']})" for _, r in df_master.iterrows()]
        selected_idx = st.selectbox("Selecciona un partido real de la jornada para cargar sus datos:", range(len(match_labels)), format_func=lambda i: match_labels[i])
        sel_row = df_master.iloc[selected_idx]

        # Obtener cuotas guardadas de ese partido si existen
        m_id = int(sel_row["match_id"])
        df_o = load_query_df("SELECT selection, odd_value FROM odds_snapshots WHERE match_id = ? AND market = '1X2';", (m_id,))
        o_dict = {r["selection"]: float(r["odd_value"]) for _, r in df_o.iterrows()}

        c1, c2 = st.columns(2)
        with c1:
            st.markdown(f"#### 📊 Datos de **{sel_row['Local']}** vs **{sel_row['Visitante']}**")
            st.write(f"**Hora del partido:** {sel_row['Hora_Local']}")
            st.write(f"**Analisis del sistema:** {sel_row['reasoning_json']}")
            lh_def = 1.60
            la_def = 1.15
            lh = st.slider(f"Goles esperados de {sel_row['Local']} (Local)", 0.30, 4.00, lh_def, 0.05)
            la = st.slider(f"Goles esperados de {sel_row['Visitante']} (Visitante)", 0.30, 4.00, la_def, 0.05)
        with c2:
            st.markdown("#### 💰 Introduce las Cuotas de tu Casa de Apuestas")
            o1 = st.number_input(f"Cuota 1 - Gana {sel_row['Local']}", 1.02, 30.0, o_dict.get("HOME", 2.00), 0.02)
            ox = st.number_input("Cuota X - Empate", 1.02, 30.0, o_dict.get("DRAW", 3.40), 0.05)
            o2 = st.number_input(f"Cuota 2 - Gana {sel_row['Visitante']}", 1.02, 30.0, o_dict.get("AWAY", 3.80), 0.05)

        probs = QuantStatsAgent.calculate_match_probabilities(lh, la)
        eval_rows = []
        for label, p_val, odd_v in [
            (f"1 - Gana {sel_row['Local']}", float(probs["p_home"]), o1),
            ("X - Empate", float(probs["p_draw"]), ox),
            (f"2 - Gana {sel_row['Visitante']}", float(probs["p_away"]), o2),
        ]:
            ev_res = MarketOddsAgent.analyze_market_value(p_val, odd_v)
            eval_rows.append({
                "Mercado": label,
                "Probabilidad Modelo": f"{p_val*100:.1f}%",
                "Cuota Minima Justa (Sin Margen)": round(1.0 / p_val, 2),
                "Cuota en tu Casa": odd_v,
                "Valor Esperado (EV)": f"{ev_res['expected_value']*100:+.1f}%",
                "¿Merece la pena?": "✅ SI (HAY VALOR)" if ev_res["has_value"] else "⛔ NO APOSTAR (Cuota baja)"
            })
        st.dataframe(pd.DataFrame(eval_rows), use_container_width=True, hide_index=True)


# ==============================================================================
# 4. MONITOR EN DIRECTO (LIVE)
# ==============================================================================
elif menu.startswith("⚡"):
    st.markdown("## ⚡ Radar de Partidos en Directo (Agentes 7 y 8)")
    df_live = df_master[df_master["status"] == "LIVE"] if not df_master.empty else pd.DataFrame()

    if df_live.empty:
        st.info("En este minuto exacto no hay partidos en estado 'EN JUEGO' dentro de las 7 competiciones. En cuanto comience el primer partido del dia y pulses Actualizar, aparecera aqui en tiempo real.")
    else:
        for _, lv in df_live.iterrows():
            st.markdown(f"""
            <div class="decision-card" style="border-left: 5px solid #ef4444;">
                <div style="color:#f87171; font-weight:800;">🔴 EN DIRECTO · {lv['Liga']} ({lv['Hora_Local']})</div>
                <div style="font-size:1.4rem; font-weight:800; margin-top:6px;">
                    {lv['Local']} <span style="color:#fbbf24; margin:0 10px;">{int(lv['home_score'] or 0)} - {int(lv['away_score'] or 0)}</span> {lv['Visitante']}
                </div>
            </div>
            """, unsafe_allow_html=True)

    st.markdown("#### Alertas Reales Emitidas en Directo")
    df_la = load_query_df("SELECT * FROM live_alerts ORDER BY alert_id DESC;")
    if df_la.empty:
        st.caption("No hay alertas de directo activas (se eliminaron las alertas simuladas de prueba).")
    else:
        st.dataframe(df_la, use_container_width=True, hide_index=True)


# ==============================================================================
# 5. ESTADO DE LOS AGENTES
# ==============================================================================
elif menu.startswith("🤖"):
    st.markdown("## 🤖 Estado y Control de los Agentes Especializados")
    df_ag = load_query_df("SELECT * FROM agent_status;")
    st.dataframe(df_ag, use_container_width=True, hide_index=True)


# ==============================================================================
# 6. RENDIMIENTO Y BRIER SCORE
# ==============================================================================
elif menu.startswith("📈"):
    st.markdown("## 📈 Evaluacion de Resultados Reales y Calibracion (Agente 10)")
    perf = AuditorAgent.get_global_performance_summary()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Pronosticos Evaluados", perf["total_evaluated"])
    c2.metric("Acierto (%)", f"{perf['win_rate']}%")
    c3.metric("Brier Score Medio", perf["avg_brier"])
    c4.metric("Yield Teorico", f"{perf['theoretical_yield']:+.2f}%")
    st.info(perf["sample_warning"])


# ==============================================================================
# 7. CONFIGURACION Y TELEGRAM
# ==============================================================================
elif menu.startswith("⚙️"):
    st.markdown("## ⚙️ Configuracion de APIs y Conexion con Telegram")
    creds_info = [
        {"Servicio": "football-data.org (Calendario y Clasificacion Real)", "Conectado": settings.is_key_configured(settings.football_data_api_key)},
        {"Servicio": "The Odds API (Cuotas Europeas Reales)", "Conectado": settings.is_key_configured(settings.odds_api_key)},
        {"Servicio": "SportScore (Estadisticas en Vivo)", "Conectado": settings.is_key_configured(settings.sportscore_api_key)},
        {"Servicio": "Gemini AI API", "Conectado": settings.is_key_configured(settings.gemini_api_key)},
        {"Servicio": "Telegram Bot", "Conectado": settings.is_key_configured(settings.telegram_bot_token)},
    ]
    st.dataframe(pd.DataFrame(creds_info), use_container_width=True, hide_index=True)

    if st.button("📲 Enviar Resumen de Oportunidades Reales de Hoy a mi Telegram"):
        opps = df_master[df_master["decision"].isin(["OPORTUNIDAD", "VIGILAR"])] if not df_master.empty else pd.DataFrame()
        if opps.empty:
            msg = "⚽ FOOTBALL INTELLIGENCE: Jornada sincronizada. Ningun partido supera el umbral de valor (EV > 4%) ahora mismo."
        else:
            lines = ["⚽ FOOTBALL INTELLIGENCE - PARTIDOS DESTACADOS (DATOS REALES):"]
            for _, r in opps.head(5).iterrows():
                sel_txt = translate_selection(str(r["selection"]), r["Local"], r["Visitante"])
                lines.append(f"• {r['Hora_Local']} | {r['Local']} vs {r['Visitante']} -> {sel_txt} | Prob: {float(r['estimated_prob'])*100:.1f}% | Cuota: {r['observed_odd']}")
            msg = "\n".join(lines)

        res = TelegramReporterAgent.send_telegram_message(msg)
        if res["sent"]:
            st.success("Resumen real enviado a tu Telegram.")
        else:
            st.error(res["reason"])
