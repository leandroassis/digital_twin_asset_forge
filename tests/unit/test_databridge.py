import json

from asset_forge.export.aas.databridge import DatabridgeContract, write_databridge_config
from asset_forge.export.aas.solar import OpcuaVariable


def test_write_databridge_config_emits_matching_source_sink_and_route_per_variable(tmp_path):
    contracts = [
        DatabridgeContract(
            "PANEL-1529520",
            "https://example.org/asset-forge/aas/ifc/abc123/sm/opcua",
            (OpcuaVariable("CurrentDC", "IDC"), OpcuaVariable("VoltageDC", "VDC")),
        ),
        DatabridgeContract(
            "INVERTER",
            "https://example.org/asset-forge/aas/virtual/inverter/sm/opcua",
            (OpcuaVariable("PowerAC", "PAC"),),
        ),
    ]

    consumer_path, sink_path, routes_path = write_databridge_config(
        tmp_path, contracts, opcua_host="localhost", opcua_port=4840, aas_env_host="localhost", aas_env_port=8081
    )

    consumers = json.loads(consumer_path.read_text())
    sinks = json.loads(sink_path.read_text())
    routes = json.loads(routes_path.read_text())

    assert len(consumers) == len(sinks) == len(routes) == 3

    idc_consumer = next(c for c in consumers if c["uniqueId"] == "opcua-PANEL-1529520-IDC")
    assert idc_consumer["nodeInformation"] == "ns=2;s=PANEL-1529520-IDC"
    assert idc_consumer["serverUrl"] == "localhost"
    assert idc_consumer["serverPort"] == 4840

    idc_sink = next(s for s in sinks if s["uniqueId"] == "aas-PANEL-1529520-IDC")
    assert idc_sink["idShortPath"] == "CurrentDC"
    assert idc_sink["api"] == "DOT_AAS_V3"

    idc_route = next(r for r in routes if r["routeId"] == "route-PANEL-1529520-IDC")
    assert idc_route["datasource"] == "opcua-PANEL-1529520-IDC"
    assert idc_route["datasinks"] == ["aas-PANEL-1529520-IDC"]

    pac_consumer = next(c for c in consumers if c["uniqueId"] == "opcua-INVERTER-PAC")
    assert pac_consumer["nodeInformation"] == "ns=2;s=INVERTER-PAC"


def test_write_databridge_config_with_no_contracts_produces_empty_files(tmp_path):
    paths = write_databridge_config(
        tmp_path, [], opcua_host="localhost", opcua_port=4840, aas_env_host="localhost", aas_env_port=8081
    )

    for path in paths:
        assert json.loads(path.read_text()) == []
