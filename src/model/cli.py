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
    config_file: Optional[Path] = typer.Option(
        Path("config/rules.json"),
        "--config",
        "-c",
        help="Caminho para o arquivo JSON com regras e limiares de anomalia",
    ),
    aasserver_path: Optional[Path] = typer.Option(
        None, "--aasserver-path", help="Optional path to aasserver.json for tag mapping"
    ),
    # InfluxDB Connection Options
    influx_host: str = typer.Option(config.INFLUXDB_HOST, "--influx-host"),
    influx_port: int = typer.Option(config.INFLUXDB_PORT, "--influx-port"),
    influx_token: str = typer.Option(config.INFLUXDB_TOKEN, "--influx-token"),
    influx_org: str = typer.Option(config.INFLUXDB_ORG, "--influx-org"),
    influx_bucket: str = typer.Option(config.INFLUXDB_BUCKET, "--influx-bucket"),
    # Configurable Anomaly Thresholds (opcionais; sobrescrevem o arquivo de configuração se fornecidos)
    z_dirt: Optional[float] = typer.Option(None, "--z-dirt", help="Override: Current Z-Score threshold for Dirt (negative)"),
    z_overheat: Optional[float] = typer.Option(None, "--z-overheat", help="Override: Temperature Z-Score threshold for Overheating"),
    z_overcurrent: Optional[float] = typer.Option(None, "--z-overcurrent", help="Override: Current Z-Score threshold for Overcurrent"),
    night_lux: Optional[float] = typer.Option(None, "--night-lux", help="Override: Maximum lux considered as Night condition"),
    max_temp: Optional[float] = typer.Option(None, "--max-temp", help="Override: Absolute maximum safe temperature limit (°C)"),
    max_current: Optional[float] = typer.Option(None, "--max-current", help="Override: Absolute maximum safe DC current limit (A)"),
) -> None:
    """Executes the continuous spatial Z-Score anomaly detection loop."""

    def _load_effective_thresholds() -> AnomalyThresholds:
        base = AnomalyThresholds.from_file(config_file) if config_file and config_file.is_file() else AnomalyThresholds()
        if z_dirt is not None:
            base.z_score_dirt = z_dirt
        if z_overheat is not None:
            base.z_score_overheat = z_overheat
        if z_overcurrent is not None:
            base.z_score_overcurrent = z_overcurrent
        if night_lux is not None:
            base.night_lux_threshold = night_lux
        if max_temp is not None:
            base.max_safe_temperature_c = max_temp
        if max_current is not None:
            base.max_safe_current_a = max_current
        return base

    if config_file and config_file.is_file():
        logger.info(f"Carregando regras de anomalia a partir do arquivo de configuração: {config_file}")
    else:
        logger.warning(f"Arquivo de configuração {config_file} não encontrado. Utilizando limiares padrão.")

    thresholds = _load_effective_thresholds()
    logger.info(
        f"Limiares ativos: Z(Dirt)={thresholds.z_score_dirt}, Z(Overheat)={thresholds.z_score_overheat}, "
        f"Z(Overcurrent)={thresholds.z_score_overcurrent}, MaxTemp={thresholds.max_safe_temperature_c}°C, "
        f"MaxCurrent={thresholds.max_safe_current_a}A, NightLux={thresholds.night_lux_threshold}lux"
    )

    last_config_mtime: Optional[float] = None
    if config_file and config_file.is_file():
        try:
            last_config_mtime = config_file.stat().st_mtime
        except OSError:
            pass

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
        # Hot-reload automático: se o arquivo de regras for alterado em disco, recarrega
        if config_file and config_file.is_file():
            try:
                current_mtime = config_file.stat().st_mtime
                if last_config_mtime is not None and current_mtime != last_config_mtime:
                    last_config_mtime = current_mtime
                    detector.thresholds = _load_effective_thresholds()
                    logger.info(f"Arquivo {config_file} alterado! Novas regras carregadas e reaplicadas com sucesso.")
            except OSError:
                pass
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
