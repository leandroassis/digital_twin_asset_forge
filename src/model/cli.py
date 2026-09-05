"""Typer command-line interface for the AI Anomaly Detection Model."""

import time
from pathlib import Path
from typing import Optional

import typer
from loguru import logger

from asset_forge import config
from model.collector import fetch_latest_readings_from_influx, load_tag_to_global_id_map
from model.detector import AnomalyDetector
from model.notifier import AlertNotifier
from model.rules import AnomalyThresholds

app = typer.Typer(add_completion=False, help="AI Model for spatial Z-Score anomaly detection.")


@app.command("run")
def run(
    interval: float = typer.Option(5.0, "--interval", "-i", help="Interval in seconds between evaluations"),
    once: bool = typer.Option(False, "--once", help="Run a single evaluation round and exit"),
    viz_url: str = typer.Option("http://localhost:8000", "--viz-url", help="Base URL of the Web Visualizer"),
    aasserver_path: Optional[Path] = typer.Option(
        None, "--aasserver-path", help="Optional path to aasserver.json for tag mapping"
    ),
    # InfluxDB Connection Options
    influx_host: str = typer.Option(config.INFLUXDB_HOST, "--influx-host"),
    influx_port: int = typer.Option(config.INFLUXDB_PORT, "--influx-port"),
    influx_token: str = typer.Option(config.INFLUXDB_TOKEN, "--influx-token"),
    influx_org: str = typer.Option(config.INFLUXDB_ORG, "--influx-org"),
    influx_bucket: str = typer.Option(config.INFLUXDB_BUCKET, "--influx-bucket"),
    # Configurable Anomaly Thresholds
    z_dirt: float = typer.Option(-2.5, "--z-dirt", help="Current Z-Score threshold for Dirt / Soiling (negative)"),
    z_overheat: float = typer.Option(2.5, "--z-overheat", help="Temperature Z-Score threshold for Overheating"),
    z_overcurrent: float = typer.Option(3.0, "--z-overcurrent", help="Current Z-Score threshold for Overcurrent"),
    night_lux: float = typer.Option(50.0, "--night-lux", help="Maximum lux considered as Night condition"),
    max_temp: float = typer.Option(65.0, "--max-temp", help="Absolute maximum safe temperature limit (°C)"),
    max_current: float = typer.Option(16.0, "--max-current", help="Absolute maximum safe DC current limit (A)"),
) -> None:
    """Executes the continuous spatial Z-Score anomaly detection loop."""
    thresholds = AnomalyThresholds(
        night_lux_threshold=night_lux,
        z_score_dirt=z_dirt,
        z_score_overheat=z_overheat,
        z_score_overcurrent=z_overcurrent,
        max_safe_temperature_c=max_temp,
        max_safe_current_a=max_current,
    )

    detector = AnomalyDetector(thresholds=thresholds)
    notifier = AlertNotifier(viz_base_url=viz_url)

    logger.info("Carregando mapeamento de tags para GlobalIds do IFC...")
    tag_map = load_tag_to_global_id_map(aasserver_path)
    logger.info(f"Mapeamento carregado com {len(tag_map)} associações.")

    logger.info(
        f"Iniciando detector de anomalias contra InfluxDB ({influx_host}:{influx_port}/{influx_bucket}) "
        f"com intervalo de {interval}s..."
    )

    while True:
        readings = fetch_latest_readings_from_influx(
            influx_host=influx_host,
            influx_port=influx_port,
            influx_token=influx_token,
            influx_org=influx_org,
            influx_bucket=influx_bucket,
            tag_to_global_id=tag_map,
        )

        if not readings:
            logger.warning("Nenhuma leitura encontrada no InfluxDB. Aguardando dados de telemetria...")
        else:
            alerts = detector.evaluate_batch(readings)
            sync_res = notifier.sync_alerts(alerts)

            if alerts:
                logger.warning(
                    f"Avaliação concluída: {len(alerts)} anomalia(s) detectada(s) em {len(readings)} painéis! "
                    f"Alertas sincronizados com o visualizador: {sync_res}"
                )
                for alert in alerts[:5]:
                    logger.warning(f" -> [{alert.error_type}] {alert.element_id}: {alert.message}")
                if len(alerts) > 5:
                    logger.warning(f" ... e mais {len(alerts) - 5} alertas ativos.")
            else:
                logger.info(f"Avaliação concluída: {len(readings)} painéis operando normalmente sem anomalias.")

        if once:
            break

        time.sleep(interval)


if __name__ == "__main__":
    app()
