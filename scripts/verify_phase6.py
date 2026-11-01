import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from core.logger import get_logger
from core.database import init_database, get_db_connection
from agents.telegram_reporter import TelegramReporterAgent

console = Console()
logger = get_logger("VerifyPhase6")


def run_phase6_test() -> None:
    console.print(Panel.fit(
        "[bold cyan]FOOTBALL INTELLIGENCE - PRUEBA DE FASE 6 - TELEGRAM Y ANTI-SPAM[/bold cyan]",
        border_style="cyan"
    ))

    init_database()

    with get_db_connection() as conn:
        # Limpiar alertas enviadas de pruebas anteriores para probar el filtro anti-spam desde cero
        conn.execute("DELETE FROM live_alerts WHERE sent_to_telegram = 1;")
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

    live_stats_sample = {
        "home_possession": 68,
        "home_shots": 8,
        "home_shots_on_target": 4,
        "home_corners": 5
    }

    # 1. Primer intento en Minuto 32 (Debe procesarse y formatearse)
    console.print("[yellow]1. Generando y enviando primera alerta relevante (Minuto 32)...[/yellow]")
    res_1 = TelegramReporterAgent.process_and_dispatch_alert(
        match_id=1,
        home_team="Real Sociedad",
        away_team="Athletic Club",
        minute=32,
        score_str="0-1",
        alert_type="FAVORITE_TRAILING_DOMINATING",
        situation_title="El favorito esta perdiendo inesperadamente.",
        live_stats=live_stats_sample,
        analysis_text="El equipo favorito esta generando ocasiones, pero todavia no ha conseguido marcar.",
        market_interest="Revisar el mercado de doble oportunidad (1X) y los mercados de goles.",
        confidence="MEDIA",
        risks="No se dispone de informacion suficiente para confirmar que la tendencia ofensiva se mantendra."
    )

    console.print(Panel(
        res_1["formatted_message"],
        title="[bold green]Vista Previa del Mensaje Formateado (Agente 11)[/bold green]",
        border_style="green"
    ))

    # 2. Segundo intento en Minuto 35 (Mismo partido y misma alerta -> Debe ser bloqueado por el filtro Anti-Spam)
    console.print("[yellow]2. Simulando repeticion en el Minuto 35 (Prueba de Filtro Anti-Spam)...[/yellow]")
    res_2 = TelegramReporterAgent.process_and_dispatch_alert(
        match_id=1,
        home_team="Real Sociedad",
        away_team="Athletic Club",
        minute=35,
        score_str="0-1",
        alert_type="FAVORITE_TRAILING_DOMINATING",
        situation_title="El favorito esta perdiendo inesperadamente.",
        live_stats=live_stats_sample,
        analysis_text="El equipo favorito esta generando ocasiones, pero todavia no ha conseguido marcar.",
        market_interest="Revisar el mercado de doble oportunidad (1X) y los mercados de goles.",
        confidence="MEDIA",
        risks="No se dispone de informacion suficiente para confirmar que la tendencia ofensiva se mantendra."
    )

    table_tg = Table(title="Auditoria de Comunicacion y Control de Ruido - Fase 6")
    table_tg.add_column("Intento", style="cyan")
    table_tg.add_column("Minuto", style="white")
    table_tg.add_column("Bloqueado por Anti-Spam", style="magenta")
    table_tg.add_column("Estado de Entrega", style="green")

    table_tg.add_row(
        "Alerta #1 (Nueva)",
        "Min 32",
        str(res_1["filtered_by_cooldown"]),
        res_1["delivery_info"]
    )
    table_tg.add_row(
        "Alerta #2 (Repetida +3 min)",
        "Min 35",
        str(res_2["filtered_by_cooldown"]),
        res_2["delivery_info"]
    )

    console.print("")
    console.print(table_tg)
    console.print("")
    logger.info("Prueba de Fase 6 ejecutada con exito.")


if __name__ == "__main__":
    run_phase6_test()
