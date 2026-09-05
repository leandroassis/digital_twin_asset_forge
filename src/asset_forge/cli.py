"""`asset-forge` command-line interface.

    asset-forge convert <project_dir> [--output DIR] [--namespace URL]
        [--dexpi/--no-dexpi] [--aas/--no-aas] [--glb/--no-glb] [--databridge/--no-databridge]
        [--host-aas-env HOST] [--port-aas-env PORT]
        [--host-opcua HOST] [--port-opcua PORT]
    asset-forge basyx upload --aasx-path PATH [--host-aas-env ...] [--host-registry ...]
    asset-forge basyx clear [--host-aas-env ...] [--host-registry ...]
    asset-forge mock-sensor run [--aasserver-path PATH] [--host-aas-env ...] [--interval SECONDS] [--once]

`basyx upload`/`basyx clear` always target the registry too (defaults point
at the local docker-compose registry) -- registering shell descriptors is
mandatory, not opt-in.

`convert` treats `project_dir` as one project (one of `assets/`'s
subfolders): every `.ifc` file directly inside it is federated into a single
plant model, decorated, and written out, with DEXPI/AAS export as optional
follow-on stages over the same model.
"""

from pathlib import Path

import typer
from loguru import logger

from asset_forge import config
from asset_forge.exceptions import AssetForgeError, DexpiUnavailableError
from asset_forge.export.aas.package import build_and_write_aasx
from asset_forge.export.dexpi_builder import build_dexpi_model
from asset_forge.export.dexpi_export import export_dexpi
from asset_forge.export.glb import build_and_write_glb
from asset_forge.export.ifc_writer import build_plant, write_plant
from asset_forge.integration.basyx_client import BasyxClient
from mock_data.mock_sensor import app as mock_sensor_app
from model.cli import app as model_app

app = typer.Typer(add_completion=False)
basyx_app = typer.Typer(add_completion=False)
app.add_typer(basyx_app, name="basyx")
app.add_typer(mock_sensor_app, name="mock-sensor")
app.add_typer(model_app, name="model")


@app.command()
def convert(
    project_dir: Path = typer.Argument(..., help="Directory holding one project's source .ifc file(s)."),
    output: Path = typer.Option(None, "--output", "-o", help="Output directory (default: <project_dir>/output)."),
    namespace: str = typer.Option(config.DEFAULT_NAMESPACE, "--namespace", "-n"),
    dexpi: bool = typer.Option(True, "--dexpi/--no-dexpi"),
    aas: bool = typer.Option(True, "--aas/--no-aas"),
    glb: bool = typer.Option(True, "--glb/--no-glb"),
    databridge: bool = typer.Option(True, "--databridge/--no-databridge"),
    host_aas_env: str = typer.Option(config.AAS_ENV_HOST, "--host-aas-env"),
    port_aas_env: int = typer.Option(config.AAS_ENV_PORT, "--port-aas-env"),
    host_opcua: str = typer.Option(config.OPCUA_HOST, "--host-opcua"),
    port_opcua: int = typer.Option(config.OPCUA_PORT, "--port-opcua"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Federate, classify and decorate a project's .ifc file(s) into a
    single plant.ifc, then optionally export DEXPI and/or an AAS package."""
    _configure_logging(verbose)

    ifc_paths = sorted(project_dir.glob("*.ifc"))
    if not ifc_paths:
        typer.echo(f"no .ifc files found directly in {project_dir}", err=True)
        raise typer.Exit(code=1)

    output = output or (project_dir / "output")
    output.mkdir(parents=True, exist_ok=True)

    project_name = project_dir.name
    typer.echo(f"converting '{project_name}' from {len(ifc_paths)} source file(s)")

    try:
        model = build_plant(ifc_paths, show_progress=verbose)
    except AssetForgeError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    plant_path = write_plant(model, output / "ifc" / "plant.ifc")
    typer.echo(f"wrote {plant_path}")

    if dexpi:
        try:
            dexpi_model = build_dexpi_model(model, project_name)
        except DexpiUnavailableError as exc:
            typer.echo(f"DEXPI skipped: {exc}", err=True)
        else:
            summary = export_dexpi(dexpi_model, output / "dexpi")
            typer.echo(
                f"wrote DEXPI export to {summary.json_path.parent} "
                f"({summary.piping_item_count} item(s), {summary.connection_count} connection(s))"
            )

    if aas:
        aasx_paths = build_and_write_aasx(
            model,
            output / "aas",
            namespace=namespace,
            opcua_host=host_opcua,
            opcua_port=port_opcua,
            databridge_dir=config.DATABRIDGE_DIR if databridge else None,
            aas_env_host=host_aas_env,
            aas_env_port=port_aas_env,
        )
        for aasx_path in aasx_paths:
            typer.echo(f"wrote {aasx_path}")

    if glb:
        glb_path = build_and_write_glb(model, output / "glb" / "plant.glb")
        typer.echo(f"wrote {glb_path}")


@basyx_app.command("upload")
def basyx_upload(
    aasx_path: Path = typer.Option(..., "--aasx-path", "-a", exists=True),
    host_aas_env: str = typer.Option(config.AAS_ENV_HOST, "--host-aas-env"),
    port_aas_env: int = typer.Option(config.AAS_ENV_PORT, "--port-aas-env"),
    host_registry: str = typer.Option(config.AAS_REGISTRY_HOST, "--host-registry"),
    port_registry: int = typer.Option(config.AAS_REGISTRY_PORT, "--port-registry"),
) -> None:
    """Upload an .aasx package to the BaSyx environment and register its
    shell descriptor(s) in the registry."""
    client = BasyxClient(
        aas_env_host=host_aas_env,
        aas_env_port=port_aas_env,
        registry_host=host_registry,
        registry_port=port_registry,
    )
    try:
        client.upload(aasx_path)
    except AssetForgeError as exc:
        typer.echo(f"upload failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"uploaded {aasx_path}")


@basyx_app.command("clear")
def basyx_clear(
    host_aas_env: str = typer.Option(config.AAS_ENV_HOST, "--host-aas-env"),
    port_aas_env: int = typer.Option(config.AAS_ENV_PORT, "--port-aas-env"),
    host_registry: str = typer.Option(config.AAS_REGISTRY_HOST, "--host-registry"),
    port_registry: int = typer.Option(config.AAS_REGISTRY_PORT, "--port-registry"),
) -> None:
    """Delete every shell/submodel, and their registry descriptors, from the
    BaSyx deployment."""
    client = BasyxClient(
        aas_env_host=host_aas_env,
        aas_env_port=port_aas_env,
        registry_host=host_registry,
        registry_port=port_registry,
    )
    client.clear()
    typer.echo("cleared")


def _configure_logging(verbose: bool) -> None:
    import sys

    logger.remove()
    logger.add(sys.stderr, level="DEBUG" if verbose else "INFO")


if __name__ == "__main__":
    app()
