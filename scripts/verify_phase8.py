import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from core.logger import get_logger
from core.database import init_database, get_db_connection
from agents.auditor import AuditorAgent

console = Console()
logger = get_logger("VerifyPhase8")


def run_phase8_test() -> None:
    console.print(Panel.fit(
        "[bold cyan]FOOTBALL INTELLIGENCE - PRUEBA DE FASE 8 - EVALUADOR BRIER SCORE Y YIELD[/bold cyan]",
        border_style="cyan"
    ))

    init_database()

    with get_db_connection() as conn:
        pred_row = conn.execute("SELECT prediction_id FROM predictions_audit ORDER BY prediction_id DESC LIMIT 1;").fetchone()
        if not pred_row:
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
            VALUES (1, 'ES_LALIGA', 1, 2, '2026-11-02 20:00:00', 'FINISHED', '2026-11-01 00:00:00');
            """)
            conn.execute("""
            INSERT INTO predictions_audit (
                match_id, stage, market, selection, estimated_prob, observed_odd,
                fair_prob_market, expected_value, confidence_level, decision, reasoning_json, created_at_utc
            ) VALUES (1, 'PREMATCH', '1X2', 'HOME', 0.58, 1.85, 0.54, 0.073, 'MEDIA', 'OPORTUNIDAD', '[]', '2026-11-01 10:00:00');
            """)
            pred_id = conn.execute("SELECT last_insert_rowid() as id;").fetchone()["id"]
        else:
            pred_id = pred_row["prediction_id"]

    console.print(f"[yellow]Liquidando prediccion ID={pred_id} con resultado cumplido (1) y calculando Brier Score...[/yellow]")
    settled = AuditorAgent.settle_prediction(prediction_id=pred_id, actual_outcome=1)
    summary = AuditorAgent.get_global_performance_summary()

    table_aud = Table(title="Metricas de Calibracion y Rendimiento Acumulado - Agente 10")
    table_aud.add_column("Metrica Estadistica", style="cyan")
    table_aud.add_column("Valor Calculado", style="green")

    table_aud.add_row("Predicciones Evaluadas", str(summary["total_evaluated"]))
    table_aud.add_row("Porcentaje de Acierto", f"{summary['win_rate']}%")
    table_aud.add_row("Brier Score (Calibracion)", f"{settled.get('brier_score', summary['avg_brier'])} (Optimo < 0.2200)")
    table_aud.add_row("Log Loss", str(settled.get("log_loss", summary["avg_log_loss"])))
    table_aud.add_row("Beneficio Teorico (Unidades)", f"{summary['theoretical_profit_units']:+.2f} u.")
    table_aud.add_row("Yield Teorico", f"{summary['theoretical_yield']:+.2f}%")
    table_aud.add_row("Control Anti-Sobreajuste", summary["sample_warning"])

    console.print("")
    console.print(table_aud)
    console.print("")
    logger.info("Prueba de Fase 8 completada con exito.")


if __name__ == "__main__":
    run_phase8_test()
