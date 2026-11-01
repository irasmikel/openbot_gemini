import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Generator
from core.config import settings
from core.logger import get_logger

logger = get_logger("DatabaseEngine")

# Las 7 competiciones prioritarias definidas en la arquitectura
INITIAL_COMPETITIONS = [
    ("ES_LALIGA", "LaLiga Española", "Spain", "PD", "soccer_spain_la_liga", 1),
    ("EN_PL", "Premier League", "England", "PL", "soccer_epl", 1),
    ("IT_SERIEA", "Serie A Italiana", "Italy", "SA", "soccer_italy_serie_a", 1),
    ("DE_BUNDESLIGA", "Bundesliga Alemana", "Germany", "BL1", "soccer_germany_bundesliga", 1),
    ("FR_LIGUE1", "Ligue 1 Francesa", "France", "FL1", "soccer_france_ligue_one", 1),
    ("EU_UCL", "UEFA Champions League", "Europe", "CL", "soccer_uefa_champs_league", 1),
    ("EU_UEL", "UEFA Europa League", "Europe", "EL", "soccer_uefa_europa_league", 1),
]

# Registro inicial de los agentes de la arquitectura para el Panel de Control
INITIAL_AGENTS = [
    ("AGENT_01_ORCHESTRATOR", "Coordinador General", "Gestiona horarios, flujos y prioridades"),
    ("AGENT_09_DATAGUARD", "Verificador de Datos", "Valida integridad, fechas, IDs y antiguedad de cuotas"),
    ("AGENT_02_QUANTSTATS", "Analista Estadistico Previo", "Calcula Poisson, Dixon-Coles, Elo y tendencias"),
    ("AGENT_03_MARKETODDS", "Analista de Cuotas y Mercados", "Extrae margen (vig), Fair Odds y Valor Esperado"),
    ("AGENT_04_05_CONTEXT", "Analista de Contexto y Tactica", "Evalua bajas, calendario, fatiga y encaje tactico"),
    ("AGENT_06_PREMATCH_OPP", "Detector de Oportunidades Previas", "Cruza estadistica, cuotas y contexto (incluye NO APOSTAR)"),
    ("AGENT_07_08_LIVE", "Supervisor y Detector en Directo", "Vigila partidos activos, indice de presion y anomalias"),
    ("AGENT_10_11_AUDITOR", "Evaluador (Brier/ROI) y Comunicador", "Audita resultados, calibra modelos y notifica en Telegram"),
]


@contextmanager
def get_db_connection() -> Generator[sqlite3.Connection, None, None]:
    """
    Proporciona una conexion segura a SQLite configurada en modo WAL
    para permitir concurrencia entre los agentes en segundo plano y la interfaz.
    """
    db_path = settings.full_db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path), timeout=20.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"Error en transaccion de base de datos: {e}")
        raise
    finally:
        conn.close()


def init_database() -> None:
    """Crea todas las tablas del sistema e inserta el catalogo inicial si no existen."""
    logger.info("Inicializando esquema de base de datos SQLite...")

    with get_db_connection() as conn:
        cursor = conn.cursor()

        # 1. Tabla maestra de competiciones (Evita errores 404 mapeando IDs por proveedor)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS competitions (
            canonical_code TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            country TEXT NOT NULL,
            sportscore_league_id INTEGER NULL,
            sportscore_season_id INTEGER NULL,
            football_data_code TEXT NULL,
            odds_api_key TEXT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            last_synced_utc TEXT NULL
        );
        """)

        # 2. Tabla maestra de equipos y resolucion de nombres (Entity Resolution)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS teams (
            team_id INTEGER PRIMARY KEY AUTOINCREMENT,
            canonical_name TEXT NOT NULL UNIQUE,
            competition_code TEXT NOT NULL,
            sportscore_team_id INTEGER NULL,
            football_data_team_id INTEGER NULL,
            odds_api_team_name TEXT NULL,
            aliases_json TEXT NOT NULL DEFAULT '[]',
            elo_rating REAL NOT NULL DEFAULT 1500.0,
            updated_at_utc TEXT NOT NULL,
            FOREIGN KEY (competition_code) REFERENCES competitions(canonical_code)
        );
        """)

        # 3. Tabla de partidos (Calendario, Estado en Directo y Resultados)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS matches (
            match_id INTEGER PRIMARY KEY AUTOINCREMENT,
            competition_code TEXT NOT NULL,
            home_team_id INTEGER NOT NULL,
            away_team_id INTEGER NOT NULL,
            kickoff_utc TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'SCHEDULED', -- SCHEDULED, LIVE, FINISHED, POSTPONED
            minute INTEGER NULL,
            home_score INTEGER NULL,
            away_score INTEGER NULL,
            sportscore_event_id INTEGER NULL UNIQUE,
            football_data_match_id INTEGER NULL UNIQUE,
            odds_api_event_id TEXT NULL,
            priority_watch INTEGER NOT NULL DEFAULT 0,
            last_updated_utc TEXT NOT NULL,
            FOREIGN KEY (competition_code) REFERENCES competitions(canonical_code),
            FOREIGN KEY (home_team_id) REFERENCES teams(team_id),
            FOREIGN KEY (away_team_id) REFERENCES teams(team_id)
        );
        """)

        # 4. Tabla de capturas de cuotas y mercado (Agente 3)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS odds_snapshots (
            snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id INTEGER NOT NULL,
            bookmaker TEXT NOT NULL,
            market TEXT NOT NULL, -- 1X2, OVER_UNDER_25, BTTS, DOUBLE_CHANCE
            selection TEXT NOT NULL, -- HOME, DRAW, AWAY, OVER, UNDER, YES, NO
            odd_value REAL NOT NULL,
            implied_prob_raw REAL NOT NULL,
            implied_prob_fair REAL NOT NULL,
            market_margin REAL NOT NULL,
            captured_at_utc TEXT NOT NULL,
            FOREIGN KEY (match_id) REFERENCES matches(match_id)
        );
        """)

        # 5. Tabla de analisis previo, predicciones y evaluacion Brier Score (Agentes 2, 6 y 10)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS predictions_audit (
            prediction_id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id INTEGER NOT NULL,
            stage TEXT NOT NULL, -- PREMATCH o LIVE
            market TEXT NOT NULL,
            selection TEXT NOT NULL,
            estimated_prob REAL NOT NULL,
            observed_odd REAL NULL,
            fair_prob_market REAL NULL,
            expected_value REAL NULL,
            confidence_level TEXT NOT NULL, -- ALTA, MEDIA, BAJA
            decision TEXT NOT NULL, -- OPORTUNIDAD, VIGILAR, NO_APOSTAR
            reasoning_json TEXT NOT NULL,
            actual_outcome INTEGER NULL, -- 1 (Cumplido), 0 (Fallido), NULL (Pendiente)
            brier_score REAL NULL,
            log_loss REAL NULL,
            created_at_utc TEXT NOT NULL,
            evaluated_at_utc TEXT NULL,
            FOREIGN KEY (match_id) REFERENCES matches(match_id)
        );
        """)

        # 6. Tabla de instantaneas en directo y alertas enviadas (Agentes 7, 8 y 11)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS live_alerts (
            alert_id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id INTEGER NOT NULL,
            minute INTEGER NOT NULL,
            score_snapshot TEXT NOT NULL,
            alert_type TEXT NOT NULL, -- FAVORITE_TRAILING, HIGH_PRESSURE_GOALLESS, RED_CARD_SHIFT
            stats_snapshot_json TEXT NOT NULL,
            analysis_text TEXT NOT NULL,
            sent_to_telegram INTEGER NOT NULL DEFAULT 0,
            created_at_utc TEXT NOT NULL,
            FOREIGN KEY (match_id) REFERENCES matches(match_id)
        );
        """)

        # 7. Tabla de estado y salud de los Agentes (Para supervision y Panel de Control)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS agent_status (
            agent_code TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            description TEXT NOT NULL,
            is_enabled INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'IDLE', -- IDLE, RUNNING, ERROR
            last_run_utc TEXT NULL,
            last_error TEXT NULL,
            total_runs INTEGER NOT NULL DEFAULT 0
        );
        """)

        # 8. Tabla de control de consumo de APIs (Evita sobrepasar limites gratuitos)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS api_usage_log (
            usage_id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT NOT NULL, -- SPORTSCORE, FOOTBALL_DATA, ODDS_API, API_FOOTBALL, GEMINI
            endpoint TEXT NOT NULL,
            status_code INTEGER NOT NULL,
            called_date_utc TEXT NOT NULL, -- YYYY-MM-DD para conteo diario rapido
            called_timestamp_utc TEXT NOT NULL
        );
        """)

        # Semilla de las 7 competiciones
        cursor.executemany("""
        INSERT OR IGNORE INTO competitions (
            canonical_code, name, country, football_data_code, odds_api_key, is_active
        ) VALUES (?, ?, ?, ?, ?, ?);
        """, INITIAL_COMPETITIONS)

        # Semilla de los agentes del sistema
        cursor.executemany("""
        INSERT OR IGNORE INTO agent_status (
            agent_code, display_name, description
        ) VALUES (?, ?, ?);
        """, INITIAL_AGENTS)

    logger.info("Base de datos inicializada y verificada correctamente.")


def record_agent_heartbeat(agent_code: str, status: str = "IDLE", error_msg: str = None) -> None:
    """Actualiza el estado de un agente en la base de datos para supervision."""
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    with get_db_connection() as conn:
        conn.execute("""
        UPDATE agent_status
        SET status = ?,
            last_run_utc = ?,
            last_error = ?,
            total_runs = total_runs + 1
        WHERE agent_code = ?;
        """, (status, now_str, error_msg, agent_code))


def get_daily_api_calls(provider: str) -> int:
    """Devuelve el numero de peticiones realizadas hoy a un proveedor especifico."""
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with get_db_connection() as conn:
        row = conn.execute("""
        SELECT COUNT(*) as total
        FROM api_usage_log
        WHERE provider = ? AND called_date_utc = ?;
        """, (provider.upper(), today_str)).fetchone()
        return int(row["total"]) if row else 0
