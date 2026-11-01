import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from core.logger import get_logger
from agents.dataguard import DataGuardAgent
from agents.quantstats import QuantStatsAgent
from agents.marketodds import MarketOddsAgent

console = Console()
logger = get_logger("VerifyPhase3")


def run_phase3_test() -> None:
    console.print(Panel.fit(
        "[bold cyan]FOOTBALL INTELLIGENCE - PRUEBA DE FASE 3 (AGENTES 2, 3 Y 9)[/bold cyan]",
        border_style="cyan"
    ))

    # 1. Prueba Agente 9 (DataGuard)
    console.print("[yellow]Probando Agente 9 (Verificador de Datos)...[/yellow]")
    dg_result = DataGuardAgent.validate_match_data(match_id=999) # ID falso para probar control de errores
    console.print(f"Resultado validación partido inexistente: [bold]{dg_result}[/bold] (Esperado: False)")

    # 2. Prueba Agente 2 (QuantStats - Poisson)
    console.print("[yellow]Probando Agente 2 (Modelo Estadístico Poisson)...[/yellow]")
    # Simulamos un partido con λ_home = 1.70 y λ_away = 1.10
    probs = QuantStatsAgent.calculate_match_probabilities(1.70, 1.10)
    
    table_stats = Table(title="Probabilidades Estadísticas Estimadas (Poisson)")
    table_stats.add_column("Mercado", style="cyan")
    table_stats.add_column("Probabilidad Estimada", style="green")
    
    table_stats.add_row("Victoria Local (1)", f"{probs['p_home']*100:.2f}%")
    table_stats.add_row("Empate (X)", f"{probs['p_draw']*100:.2f}%")
    table_stats.add_row("Victoria Visitante (2)", f"{probs['p_away']*100:.2f}%")
    table_stats.add_row("Más de 2.5 Goles", f"{probs['p_over_25']*100:.2f}%")
    console.print(table_stats)
    console.print("")

    # 3. Prueba Agente 3 (MarketOdds - Valor Esperado)
    console.print("[yellow]Probando Agente 3 (Cálculo de Valor Esperado EV)...[/yellow]")
    # Supongamos que estimamos un 55% (0.55) de probabilidad para la victoria local y la casa paga a cuota 2.05
    ev_result = MarketOddsAgent.analyze_market_value(estimated_prob=0.55, observed_odd=2.05)
    
    table_ev = Table(title="Análisis de Valor de Mercado")
    table_ev.add_column("Parámetro", style="white")
    table_ev.add_column("Valor", style="magenta")

    table_ev.add_row("Probabilidad Estimada (Modelo)", f"{ev_result['estimated_prob']*100:.1f}%")
    table_ev.add_row("Cuota Observada (Casa)", str(ev_result['observed_odd']))
    table_ev.add_row("Probabilidad Implícita", f"{ev_result['implied_prob']*100:.1f}%")
    table_ev.add_row("Valor Esperado (EV)", f"+{ev_result['expected_value']*100:.1f}%")
    table_ev.add_row("Decisión del Sistema", f"[bold green]{ev_result['recommendation']}[/bold green]")
    console.print(table_ev)

    logger.info("Prueba de Fase 3 ejecutada con éxito.")


if __name__ == "__main__":
    run_phase3_test()
