"""Typer command-line interface for the AI Anomaly Detection Model."""

import time
from pathlib import Path
from typing import Optional

import requests
import typer
from loguru import logger

from asset_forge import config
from asset_forge.integration.timeseries import resolve_timeseries_targets
from model.collector import fetch_latest_readings
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
    host_aas_env: str = typer.Option(config.AAS_ENV_HOST, "--host-aas-env"),
    port_aas_env: int = typer.Option(config.AAS_ENV_PORT, "--port-aas-env"),
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
    session = requests.Session()

    logger.info(f"Resolvendo alvos de timeseries via BaSyx ({host_aas_env}:{port_aas_env})...")
    targets = resolve_timeseries_targets(host_aas_env, port_aas_env, session=session)
    logger.info(f"{len(targets)} alvo(s) de timeseries resolvido(s) (painéis + inversor).")

    logger.info(f"Iniciando detector de anomalias com intervalo de {interval}s...")

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
        readings = fetch_latest_readings(targets, session=session)

        if not readings:
            logger.warning("Nenhuma leitura encontrada via BaSyx/history-api. Aguardando dados de telemetria...")
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
