import httpx
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from core.config import settings
from core.logger import get_logger
from core.database import get_db_connection, record_agent_heartbeat

logger = get_logger("Agent11_TelegramReporter")


class TelegramReporterAgent:
    """
    AGENTE 11: Informes y Comunicacion via Telegram.
    Formatea las alertas con la plantilla profesional definida, aplica filtro
    anti-spam (cooldown por partido y tipo de alerta) y envia mensajes reales
    al movil si TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID estan configurados.
    """

    @staticmethod
    def format_live_alert_message(
        home_team: str,
        away_team: str,
        minute: int,
        score_str: str,
        situation_title: str,
        live_stats: Dict[str, Any],
        analysis_text: str,
        market_interest: str,
        confidence: str,
        risks: str
    ) -> str:
        """Genera exactamente el formato de notificacion solicitado en la especificacion."""
        poss = live_stats.get("home_possession", 50)
        shots = live_stats.get("home_shots", 0)
        sot = live_stats.get("home_shots_on_target", 0)
        corners = live_stats.get("home_corners", 0)

        msg_lines = [
            f"PARTIDO: {home_team} - {away_team}",
            f"MINUTO: {minute}",
            f"RESULTADO: {score_str}",
            "SITUACION:",
            f"{situation_title}",
            "DATOS:",
            f"- {poss} % de posesion.",
            f"- {shots} tiros.",
            f"- {sot} tiros a puerta.",
            f"- {corners} corneres.",
            "ANALISIS:",
            f"{analysis_text}",
            "POSIBLE INTERES:",
            f"{market_interest}",
            f"CONFIANZA DEL ANALISIS: {confidence}.",
            "RIESGOS:",
            f"{risks}"
        ]
        return "\n".join(msg_lines)

    @staticmethod
    def is_duplicate_alert(match_id: int, alert_type: str, current_minute: int, cooldown_minutes: int = 20) -> bool:
        """
        Filtro anti-spam: comprueba si ya se ha enviado una alerta del mismo tipo
        para este partido dentro de la ventana de enfriamiento (cooldown).
        """
        with get_db_connection() as conn:
            row = conn.execute("""
            SELECT minute FROM live_alerts
            WHERE match_id = ? AND alert_type = ? AND sent_to_telegram = 1
            ORDER BY alert_id DESC LIMIT 1;
            """, (match_id, alert_type)).fetchone()

            if row:
                last_min = int(row["minute"])
                if abs(current_minute - last_min) < cooldown_minutes:
                    logger.info(f"Filtro Anti-Spam activado: Alerta {alert_type} omitida (ultima en min {last_min}, actual min {current_minute}).")
                    return True
        return False

    @classmethod
    def send_telegram_message(cls, text: str, disable_notification: bool = False) -> Dict[str, Any]:
        """Envia el mensaje a la API de Telegram si las credenciales estan completas."""
        has_token = settings.is_key_configured(settings.telegram_bot_token)
        chat_id = (settings.telegram_chat_id or "").strip()

        if not has_token or not chat_id:
            logger.warning("Falta TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID en .env. Se ejecuta en modo simulacion local.")
            return {
                "sent": False,
                "mode": "SIMULATION_MISSING_CHAT_ID" if has_token else "SIMULATION_MISSING_TOKEN",
                "reason": "Configura TELEGRAM_CHAT_ID en tu archivo .env para recibir el mensaje en tu movil."
            }

        token_val = settings.telegram_bot_token.get_secret_value().strip()
        url = f"https://api.telegram.org/bot{token_val}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "disable_notification": disable_notification
        }

        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(url, json=payload)
                now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

                with get_db_connection() as conn:
                    conn.execute("""
                    INSERT INTO api_usage_log (provider, endpoint, status_code, called_date_utc, called_timestamp_utc)
                    VALUES ('TELEGRAM', '/sendMessage', ?, ?, ?);
                    """, (resp.status_code, today_str, now_str))

                if resp.status_code == 200:
                    logger.info("Notificacion enviada a Telegram con exito.")
                    return {"sent": True, "mode": "LIVE_TELEGRAM", "reason": "Enviado correctamente al movil."}
                else:
                    logger.error(f"Error devuelto por Telegram ({resp.status_code}): {resp.text}")
                    return {"sent": False, "mode": "API_ERROR", "reason": f"HTTP {resp.status_code}: {resp.text}"}
        except Exception as e:
            logger.error(f"Error de red conectando con Telegram: {e}")
            return {"sent": False, "mode": "NETWORK_ERROR", "reason": str(e)}

    @classmethod
    def process_and_dispatch_alert(
        cls,
        match_id: int,
        home_team: str,
        away_team: str,
        minute: int,
        score_str: str,
        alert_type: str,
        situation_title: str,
        live_stats: Dict[str, Any],
        analysis_text: str,
        market_interest: str,
        confidence: str,
        risks: str
    ) -> Dict[str, Any]:
        """Evalua el filtro anti-spam, formatea la alerta, la envia y actualiza SQLite."""
        record_agent_heartbeat("AGENT_10_11_AUDITOR", status="RUNNING")

        if cls.is_duplicate_alert(match_id, alert_type, minute):
            record_agent_heartbeat("AGENT_10_11_AUDITOR", status="IDLE")
            return {
                "dispatched": False,
                "filtered_by_cooldown": True,
                "formatted_message": "",
                "delivery_info": "Bloqueada por filtro Anti-Spam (alerta repetida en ventana de 20 min)."
            }

        formatted_msg = cls.format_live_alert_message(
            home_team=home_team,
            away_team=away_team,
            minute=minute,
            score_str=score_str,
            situation_title=situation_title,
            live_stats=live_stats,
            analysis_text=analysis_text,
            market_interest=market_interest,
            confidence=confidence,
            risks=risks
        )

        delivery = cls.send_telegram_message(formatted_msg)

        # Registrar en base de datos que la alerta ya ha sido procesada/enviada (sent_to_telegram = 1)
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        with get_db_connection() as conn:
            conn.execute("""
            INSERT INTO live_alerts (
                match_id, minute, score_snapshot, alert_type,
                stats_snapshot_json, analysis_text, sent_to_telegram, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, 1, ?);
            """, (match_id, minute, score_str, alert_type, str(live_stats), analysis_text, now_str))

        record_agent_heartbeat("AGENT_10_11_AUDITOR", status="IDLE")
        return {
            "dispatched": True,
            "filtered_by_cooldown": False,
            "formatted_message": formatted_msg,
            "delivery_info": f"{delivery['mode']} - {delivery['reason']}"
        }
