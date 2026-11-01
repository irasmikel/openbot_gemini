import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from core.logger import get_logger
from core.database import init_database, get_db_connection
from agents.live_engine import LiveEngineAgent

console = Console()
logger = get_logger("VerifyPhase5")


def run_phase5_test() -> None:
    console.print(Panel.fit(
        "[bold cyan]FOOTBALL INTELLIGENCE - PRUEBA DE FASE 5 - SEGUIMIENTO EN DIRECTO[/bold cyan]",
        border_style="cyan"
    ))

    init_database()

    with get_db_connection() as conn:
        conn.execute("""
        INSERT OR IGNORE INTO teams (team_id, canonical_name, competition_code, updated_at_utc)
        VALUES (1, 'Real Sociedad', 'ES_LALIGA', '2026-11-01 00:00:00');
        """)
        conn.execute("""
        INSERT OR IGNORE INTO teams (team_id, canonical_name, competition_code, updated_at_utc)
        VALUES (2, 'Athletic Club', 'ES_LALIGA', '2026-11-01 00:00:00');
        """)
        conn.execute("""
        INSERT OR IGNORE INTO matches (match_id, competition_code, home_team_id, away_team_id, kickoff_utc, status, last_updated_utc)
        VALUES (1, 'ES_LALIGA', 1, 2, '2026-11-01 18:30:00', 'LIVE', '2026-11-01 19:02:00');
        """)

    # Simulacion 1: Escenario A (Favorito perdiendo 0-1 en el min 32 pero asediando la porteria)
    console.print("[yellow]Simulando Caso 1: Minuto 32, Favorito perdiendo 0-1 con alto dominio ofensivo...[/yellow]")
    stats_case_a = {
        "home_possession": 68,
        "away_possession": 32,
        "home_shots": 9,
        "away_shots": 2,
        "home_shots_on_target": 5,
        "away_shots_on_target": 1,
        "home_corners": 6,
        "away_corners": 0,
        "home_dangerous_attacks": 34,
        "away_dangerous_attacks": 8,
        "home_red_cards": 0,
        "away_red_cards": 0
    }

    alerts_a = LiveEngineAgent.evaluate_live_match(
        match_id=1,
        home_team="Real Sociedad",
        away_team="Athletic Club",
        minute=32,
        home_score=0,
        away_score=1,
        prematch_fav="HOME",
        prematch_prob_fav=0.60,
        prematch_expected_goals=2.5,
        live_stats=stats_case_a
    )

    # Simulacion 2: Escenario B Inverso (Partido donde se esperaban muchos goles pero esta muerto en el min 40)
    console.print("[yellow]Simulando Caso 2: Minuto 40, Marcador 0-0 sin ocasiones pese a prevision alta de goles...[/yellow]")
    stats_case_b = {
        "home_possession": 51,
        "away_possession": 49,
        "home_shots": 1,
        "away_shots": 1,
        "home_shots_on_target": 0,
        "away_shots_on_target": 0,
        "home_corners": 1,
        "away_corners": 0,
        "home_dangerous_attacks": 6,
        "away_dangerous_attacks": 5,
        "home_red_cards": 0,
        "away_red_cards": 0
    }

    alerts_b = LiveEngineAgent.evaluate_live_match(
        match_id=1,
        home_team="Real Sociedad",
        away_team="Athletic Club",
        minute=40,
        home_score=0,
        away_score=0,
        prematch_fav="HOME",
        prematch_prob_fav=0.52,
        prematch_expected_goals=2.9,
        live_stats=stats_case_b
    )

    all_alerts = alerts_a + alerts_b

    table_live = Table(title="Alertas Generadas por el Motor en Directo - Agentes 7 y 8")
    table_live.add_column("Escenario Detectado", style="cyan")
    table_live.add_column("Diagnostico Estadistico en Vivo", style="white")
    table_live.add_column("Confianza", style="magenta")
    table_live.add_column("Accion / Filtro", style="bold green")

    for al in all_alerts:
        table_live.add_row(
            al["scenario"],
            al["situation"],
            al["confidence"],
            al["recommendation"]
        )

    console.print("")
    console.print(table_live)
    console.print("")

    with get_db_connection() as conn:
        total_saved = conn.execute("SELECT COUNT(*) as total FROM live_alerts;").fetchone()["total"]
    console.print(f"[bold green]OK Total de alertas en directo registradas en SQLite: {total_saved}[/bold green]")
    logger.info("Prueba de Fase 5 ejecutada con exito.")


if __name__ == "__main__":
    run_phase5_test()
