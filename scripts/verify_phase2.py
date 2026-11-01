import sys
from pathlib import Path

# Añadir el directorio raiz al path de Python en Windows
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from core.config import settings
from core.logger import get_logger, LOG_FILE
from core.database import init_database, get_db_connection, record_agent_heartbeat

console = Console()
logger = get_logger("VerifyPhase2")


def run_diagnostics() -> None:
    console.print(Panel.fit(
        "[bold cyan]FOOTBALL INTELLIGENCE - DIAGNOSTICO DE FASE 2 (INFRAESTRUCTURA)[/bold cyan]",
        border_style="cyan"
    ))

    # 1. Inicializar y verificar Base de Datos
    init_database()
    record_agent_heartbeat("AGENT_01_ORCHESTRATOR", status="IDLE")

    with get_db_connection() as conn:
        journal_mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
        competitions = conn.execute("SELECT * FROM competitions;").fetchall()
        agents = conn.execute("SELECT * FROM agent_status;").fetchall()

    console.print(f"[bold green]OK Base de datos SQLite operativa:[/bold green] {settings.full_db_path}")
    console.print(f"[bold green]OK Modo de concurrencia SQLite:[/bold green] {journal_mode.upper()} (Esperado: WAL)")
    console.print(f"[bold green]OK Archivo de registro (Log):[/bold green] {LOG_FILE}\n")

    # 2. Tabla de las 7 competiciones prioritarias
    comp_table = Table(title="Catalogo Maestro de Competiciones (7 Ligas Objetivo)")
    comp_table.add_column("Codigo Interno", style="cyan", no_wrap=True)
    comp_table.add_column("Competicion", style="white")
    comp_table.add_column("Cod. Football-Data", style="magenta")
    comp_table.add_column("Clave The Odds API", style="yellow")
    comp_table.add_column("ID SportScore", style="green")

    for c in competitions:
        ss_id = str(c["sportscore_league_id"]) if c["sportscore_league_id"] else "Pendiente Sync (Fase 3)"
        comp_table.add_row(
            c["canonical_code"],
            c["name"],
            c["football_data_code"],
            c["odds_api_key"],
            ss_id
        )
    console.print(comp_table)
    console.print("")

    # 3. Tabla de Agentes registrados en la base de datos
    agent_table = Table(title="Estado del Equipo de Agentes en Base de Datos")
    agent_table.add_column("Codigo Agente", style="cyan")
    agent_table.add_column("Nombre", style="white")
    agent_table.add_column("Estado", style="green")
    agent_table.add_column("Ejecuciones", justify="right")

    for a in agents:
        agent_table.add_row(
            a["agent_code"],
            a["display_name"],
            a["status"],
            str(a["total_runs"])
        )
    console.print(agent_table)
    console.print("")

    # 4. Auditoria de Credenciales en .env (Sin exponer valores)
    cred_table = Table(title="Estado de Credenciales en archivo .env (Seguridad SecretStr)")
    cred_table.add_column("Servicio / API", style="white")
    cred_table.add_column("Estado en .env", style="bold")
    cred_table.add_column("Uso en la Arquitectura", style="dim")

    checks = [
        ("SportScore (RapidAPI)", settings.sportscore_api_key, "Eventos, directo y estadisticas detalladas"),
        ("football-data.org", settings.football_data_api_key, "Calendario oficial, resultados y clasificacion"),
        ("The Odds API", settings.odds_api_key, "Cuotas de casas de apuestas y calculo de margen"),
        ("API-Football (Opcional)", settings.apifootball_api_key, "Respaldo para lesiones y alineaciones"),
        ("Gemini API (IA)", settings.gemini_api_key, "Agentes cognitivos (Contexto y Oportunidades)"),
        ("Telegram Bot Token", settings.telegram_bot_token, "Envio de informes y alertas al movil"),
    ]

    for name, secret_obj, purpose in checks:
        is_ok = settings.is_key_configured(secret_obj)
        status_label = "[green]CONFIGURADA[/green]" if is_ok else "[yellow]PENDIENTE EN .env[/yellow]"
        cred_table.add_row(name, status_label, purpose)

    console.print(cred_table)
    logger.info("Diagnostico de Fase 2 completado con exito.")


if __name__ == "__main__":
    run_diagnostics()
