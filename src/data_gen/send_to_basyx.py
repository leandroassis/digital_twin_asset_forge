"""Send physically-simulated panel readings to BaSyx.

Same write/read-back/historize pattern as mock_data/mock_sensor.py (PATCH
each opcua Property's `$value`, GET it back to confirm, historize the round
into InfluxDB) -- reused directly from there rather than duplicated. The
difference: instead of one independent random value per Property,
LightIntensity/Temperature/CurrentDC/VoltageDC for a given panel are derived
together from model_pv.maximum_power_point(), so they stay physically
consistent with each other. Each panel additionally applies its own
perturbation profile (see perturbation.py / generate_profiles_cli.py) on top
of the shared base irradiance/temperature series, so panels don't all report
identical readings.

Only panels are driven here -- the virtual inverter would need a DC->AC
aggregation model that doesn't exist yet (see the project plan).
"""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional

import pandas as pd
import requests
import typer
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
from loguru import logger

from asset_forge import config
from asset_forge.export.aas.solar import PANEL_VARIABLES
from configs import DATA_DIR, SIMULATION_START_DATETIME, SIMULATION_STEP
from mock_data.mock_sensor import SensorTarget, _value_url, load_targets
from model_pv import PVParameters, maximum_power_point
from send_data_to_OPCUA import interpolate_dataset

app = typer.Typer(add_completion=False)

PANEL_ID_SHORTS = {variable.id_short for variable in PANEL_VARIABLES}


def _write_value(session: requests.Session, host: str, port: int, target: SensorTarget, value: float) -> None:
    """Same PATCH as mock_sensor.write_value, but over a reused `Session`
    instead of opening a fresh connection per call (see the project plan --
    this module drives far more Properties per round than mock_sensor.py
    does, so connection reuse matters here)."""
    resp = session.patch(_value_url(host, port, target), json=str(value), timeout=10)
    resp.raise_for_status()


def _read_value(session: requests.Session, host: str, port: int, target: SensorTarget) -> float:
    """Same GET as mock_sensor.read_value, but over a reused `Session`."""
    resp = session.get(_value_url(host, port, target), timeout=10)
    resp.raise_for_status()
    return float(resp.json())


def panel_reading(
    base_irradiance: float,
    base_ambient_temperature: float,
    irradiance_factor: float,
    temperature_offset: float,
    parameters: PVParameters = PVParameters(),
) -> Dict[str, float]:
    """Apply one panel's perturbation profile and run the PV model.

    Args:
        base_irradiance: Shared plant-wide irradiance for this instant, in
            W/m² (before this panel's perturbation is applied).
        base_ambient_temperature: Shared plant-wide ambient temperature for
            this instant, in °C (before this panel's perturbation is
            applied).
        irradiance_factor: This panel's ``irradiance_factor`` from its
            profile row (see :func:`perturbation.generate_profiles`);
            multiplies ``base_irradiance``.
        temperature_offset: This panel's ``temperature_offset`` from its
            profile row, in °C; added to ``base_ambient_temperature``.
        parameters: Physical panel parameters passed through to
            :func:`model_pv.maximum_power_point`.

    Returns:
        A dict keyed by the panel's opcua Property id_shorts --
        ``LightIntensity``, ``Temperature``, ``CurrentDC``, ``VoltageDC``
        (matches :data:`PANEL_ID_SHORTS`). ``LightIntensity`` is the
        *perturbed* irradiance (what this specific panel "sees"), and
        ``Temperature`` is the operating point's cell temperature, not the
        raw ambient value.
    """
    irradiance = base_irradiance * irradiance_factor
    ambient_temperature = base_ambient_temperature + temperature_offset
    point = maximum_power_point(
        irradiance=irradiance, ambient_temperature=ambient_temperature, parameters=parameters
    )
    return {
        "LightIntensity": irradiance,
        "Temperature": point.cell_temperature_c,
        "CurrentDC": point.current_a,
        "VoltageDC": point.voltage_v,
    }


def _group_by_panel(targets: List[SensorTarget]) -> Dict[str, List[SensorTarget]]:
    """Group opcua Property targets by panel asset tag, panels only.

    Args:
        targets: Flat target list as returned by
            :func:`mock_data.mock_sensor.load_targets` -- panels, the
            inverter, and any other asset type mixed together.

    Returns:
        A dict mapping each panel's ``asset_tag`` (e.g. ``"PANEL-1529520"``)
        to its list of ``SensorTarget`` entries (one per opcua Property).
        Entries whose ``asset_tag`` doesn't start with ``"PANEL-"`` (e.g.
        ``"INVERTER"``) are dropped.
    """
    groups: Dict[str, List[SensorTarget]] = {}
    for target in targets:
        if target.asset_tag.startswith("PANEL-"):
            groups.setdefault(target.asset_tag, []).append(target)
    return groups


class _WriteResult(NamedTuple):
    """Outcome of one write_value + read_value pair against BaSyx."""

    asset_tag: str
    target: SensorTarget
    value: float
    readback: Optional[float]
    error: Optional[Exception]


def _write_and_verify(
    session: requests.Session, host: str, port: int, asset_tag: str, target: SensorTarget, value: float
) -> _WriteResult:
    """Run the same write-then-read-back pair as mock_sensor.py's `run()`
    loop, but as a single call so it can be submitted to a thread pool.

    Args:
        session: Shared ``requests.Session`` -- reused across every call in
            a round so concurrent write+read pairs don't each open a fresh
            TCP connection (this module drives far more Properties per
            round than mock_sensor.py does; without reuse, high
            ``--max-workers`` values can exhaust local ephemeral ports on
            Windows).
        host: BaSyx ``aas-environment`` hostname.
        port: BaSyx ``aas-environment`` port.
        asset_tag: The panel this target belongs to (carried through so the
            caller can still group results by panel after they complete out
            of order).
        target: Which submodel Property to write.
        value: The value to PATCH in.

    Returns:
        A :class:`_WriteResult` with ``readback`` set on success, or
        ``error`` set (and ``readback=None``) if either the PATCH or the GET
        raised ``requests.RequestException``.
    """
    try:
        _write_value(session, host, port, target, value)
        readback = _read_value(session, host, port, target)
        return _WriteResult(asset_tag, target, value, readback, None)
    except requests.RequestException as exc:
        return _WriteResult(asset_tag, target, value, None, exc)


@app.command()
def run(
    profiles_path: Path = typer.Option(DATA_DIR / "panel_profiles.csv", "--profiles-path", exists=True),
    aasserver_path: Path = typer.Option(
        config.DATABRIDGE_DIR / "aasserver.json", "--aasserver-path", exists=True
    ),
    host_aas_env: str = typer.Option(config.AAS_ENV_HOST, "--host-aas-env"),
    port_aas_env: int = typer.Option(config.AAS_ENV_PORT, "--port-aas-env"),
    influx_host: str = typer.Option(config.INFLUXDB_HOST, "--influx-host"),
    influx_port: int = typer.Option(config.INFLUXDB_PORT, "--influx-port"),
    influx_org: str = typer.Option(config.INFLUXDB_ORG, "--influx-org"),
    influx_bucket: str = typer.Option(config.INFLUXDB_BUCKET, "--influx-bucket"),
    influx_token: str = typer.Option(config.INFLUXDB_TOKEN, "--influx-token"),
    interval: float = typer.Option(1.0, "--interval", help="seconds between simulated rounds"),
    once: bool = typer.Option(False, "--once", help="do one round, then exit"),
    max_workers: int = typer.Option(
        1,
        "--max-workers",
        help="concurrent write+read-back pairs against BaSyx (1 = sequential); "
        "tune up based on what your machine/network/BaSyx instance can take",
    ),
) -> None:
    """Simulate the plant forward in time, writing each panel's derived
    readings into BaSyx and historizing them into InfluxDB, one round per
    ``interval`` seconds (or once, with ``--once``).

    Args:
        profiles_path: CSV produced by ``generate_profiles_cli.py`` (columns
            ``panel_tag``, ``irradiance_factor``, ``temperature_offset``).
            A panel present in ``aasserver_path`` but missing from this file
            falls back to a neutral profile (logged as a warning).
        aasserver_path: DataBridge config listing every ``(submodel,
            idShortPath)`` target, as generated by
            ``asset-forge convert --databridge``.
        host_aas_env: Hostname of the BaSyx ``aas-environment`` service.
        port_aas_env: Port of the BaSyx ``aas-environment`` service.
        influx_host: InfluxDB hostname.
        influx_port: InfluxDB port.
        influx_org: InfluxDB organization.
        influx_bucket: InfluxDB bucket to write sensor readings into.
        influx_token: InfluxDB auth token.
        interval: Seconds of wall-clock time to sleep between simulated
            rounds (ignored when ``once=True``).
        once: Run exactly one round (one simulated instant) and exit,
            instead of looping until the dataset is exhausted.
        max_workers: How many write_value/read_value pairs to run
            concurrently (thread pool). Each round is ``len(panels) * 4``
            independent pairs, so running them one at a time (the default,
            matching mock_sensor.py's sequential behavior) is dominated by
            per-request network latency, not local computation -- raising
            this trades that safety margin for speed, and the right value
            depends on this machine, the network, and how much concurrent
            load the target BaSyx instance can actually take, so there's no
            one-size-fits-all default.
    """
    profiles = pd.read_csv(profiles_path).set_index("panel_tag")

    targets = load_targets(aasserver_path)
    panels = _group_by_panel(targets)
    if not panels:
        typer.echo(f"no PANEL- targets found in {aasserver_path}", err=True)
        raise typer.Exit(code=1)

    missing_profiles = [tag for tag in panels if tag not in profiles.index]
    if missing_profiles:
        logger.warning(
            f"{len(missing_profiles)} panel(s) have no profile in {profiles_path}; "
            "using a neutral profile (factor=1.0, offset=0.0) for them"
        )

    logger.info(
        f"driving {len(panels)} panel(s) x {len(PANEL_ID_SHORTS)} Properties against "
        f"{host_aas_env}:{port_aas_env}, historizing to {influx_host}:{influx_port}/{influx_bucket}"
    )

    influx_client = InfluxDBClient(url=f"http://{influx_host}:{influx_port}", token=influx_token, org=influx_org)
    influx_write_api = influx_client.write_api(write_options=SYNCHRONOUS)

    # One Session, reused for every PATCH/GET this run makes -- pool sized
    # to max_workers so concurrent requests actually get to reuse a
    # connection instead of contending over a too-small pool.
    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(pool_connections=max_workers, pool_maxsize=max_workers)
    session.mount("http://", adapter)

    current_datetime = SIMULATION_START_DATETIME
    while True:
        try:
            base_irradiance, base_ambient_temperature = interpolate_dataset(current_datetime)
        except IndexError:
            logger.info("fim do dataset; simulacao encerrada")
            break

        # Compute every panel's reading up front (pure, in-process, cheap)
        # so the thread pool only ever does network I/O.
        tasks = []
        for asset_tag, panel_targets in panels.items():
            if asset_tag in profiles.index:
                row = profiles.loc[asset_tag]
                irradiance_factor = float(row["irradiance_factor"])
                temperature_offset = float(row["temperature_offset"])
            else:
                irradiance_factor, temperature_offset = 1.0, 0.0

            reading = panel_reading(
                base_irradiance, base_ambient_temperature, irradiance_factor, temperature_offset
            )
            for target in panel_targets:
                tasks.append((asset_tag, target, reading[target.id_short]))

        ok = mismatched = failed = 0
        round_time = datetime.now(timezone.utc)
        points_by_asset: Dict[str, Point] = {}

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(_write_and_verify, session, host_aas_env, port_aas_env, asset_tag, target, value)
                for asset_tag, target, value in tasks
            ]
            for future in as_completed(futures):
                result = future.result()

                if result.error is not None:
                    failed += 1
                    logger.warning(f"{result.asset_tag}/{result.target.id_short}: request failed: {result.error}")
                    continue

                if result.readback == result.value:
                    ok += 1
                else:
                    mismatched += 1
                    logger.warning(
                        f"{result.asset_tag}/{result.target.id_short}: "
                        f"wrote {result.value}, read back {result.readback}"
                    )

                point = points_by_asset.setdefault(
                    result.asset_tag, Point("sensor_reading").tag("asset", result.asset_tag).time(round_time)
                )
                point.field(result.target.id_short, result.readback)

        points = list(points_by_asset.values())
        if points:
            influx_write_api.write(bucket=influx_bucket, record=points)

        logger.info(
            f"round complete ({current_datetime:%d/%m/%Y %H:%M:%S}): {ok} ok, {mismatched} mismatched, "
            f"{failed} failed; historized {len(points)} panel(s) to InfluxDB"
        )

        if once:
            break
        current_datetime += SIMULATION_STEP
        time.sleep(interval)


if __name__ == "__main__":
    app()
