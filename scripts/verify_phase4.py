import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from core.logger import get_logger
from agents.context_tactical import ContextTacticalAgent
from agents.prematch_decision import PreMatchDecisionAgent
from agents.orchestrator import OrchestratorAgent
from core.database import init_database, get_db_connection

console = Console()
logger = get_logger("VerifyPhase4")


def run_phase4_test() -> None:
    console.print(Panel.fit(
        "[bold cyan]FOOTBALL INTELLIGENCE - PRUEBA DE FASE 4 - ANALISIS PREVIO Y ORQUESTADOR[/bold cyan]",
        border_style="cyan"
    ))

    init_database()

    console.print("[yellow]Probando Agentes 4 y 5 - Contexto, Bajas y Tactica...[/yellow]")
    ctx = ContextTacticalAgent.evaluate_match_context("Real Sociedad", "Athletic Club")
    console.print(f"Fatiga Visitante: [bold red]{ctx['away_fatigue_index']}[/bold red]")
    console.print(f"Bajas Visitante: {ctx['key_absences_away']}")
    console.print(f"Resumen Tactico: {ctx['tactical_matchup']}")
    console.print("")

    console.print("[yellow]Probando Agente 6 - Detector de Oportunidades Previas y EV...[/yellow]")
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
        VALUES (1, 'ES_LALIGA', 1, 2, '2026-11-02 20:00:00', 'SCHEDULED', '2026-11-01 00:00:00');
        """)

    decision = PreMatchDecisionAgent.evaluate_prematch_opportunity(
        match_id=1,
        market="1X2",
        selection="HOME",
        estimated_prob=0.58,
        observed_odd=1.85,
        context_data=ctx
    )

    table_op = Table(title="Auditoria de Oportunidad Previa - Agente 6")
    table_op.add_column("Parametro", style="white")
    table_op.add_column("Resultado", style="magenta")

    table_op.add_row("Mercado / Seleccion", f"{decision['market']} - {decision['selection']}")
    table_op.add_row("Probabilidad Estimada", f"{decision['estimated_prob']*100:.1f}%")
    table_op.add_row("Cuota Observada", str(decision['observed_odd']))
    table_op.add_row("Valor Esperado EV", f"+{decision['expected_value']*100:.1f}%")
    table_op.add_row("Nivel de Confianza", decision['confidence'])
    table_op.add_row("Decision Final", f"[bold green]{decision['decision']}[/bold green]")
    console.print(table_op)
    console.print("")

    console.print("[yellow]Probando Agente 1 - Coordinador General...[/yellow]")
    OrchestratorAgent.run_daily_prematch_pipeline()
    console.print("[bold green]OK Pipeline del Coordinador ejecutado y registrado en BD correctamente.[/bold green]")
    console.print("")

    logger.info("Prueba de Fase 4 ejecutada con exito.")


if __name__ == "__main__":
    run_phase4_test()
