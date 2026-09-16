from unittest.mock import MagicMock

from asset_forge.integration.timeseries import TimeseriesTarget, resolve_timeseries_targets


def _response(status_code=200, json_body=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json = MagicMock(return_value=json_body if json_body is not None else {})
    resp.raise_for_status = MagicMock()
    return resp


def _shell(shell_id, timeseries_submodel_id=None):
    submodels = []
    if timeseries_submodel_id:
        submodels.append({"keys": [{"value": timeseries_submodel_id}]})
    return {"id": shell_id, "submodels": submodels}


def _timeseries_elements(endpoint, query):
    return {
        "result": [
            {
                "idShort": "Segments",
                "value": [
                    {
                        "idShort": "LinkedSegment",
                        "value": [
                            {"idShort": "Endpoint", "value": endpoint},
                            {"idShort": "Query", "value": query},
                        ],
                    }
                ],
            }
        ]
    }


def test_resolves_panel_target_and_extracts_global_id():
    session = MagicMock()
    panel_shell_id = "https://example.org/asset-forge/aas/ifc/2QF3$F$XHF1A$PuubJ8dJ8"
    ts_id = f"{panel_shell_id}/sm/timeseries"

    session.get.side_effect = [
        _response(json_body={"result": [_shell(panel_shell_id, ts_id)]}),
        _response(json_body=_timeseries_elements("http://localhost:8090", "PANEL-1529520")),
    ]

    targets = resolve_timeseries_targets("localhost", 8081, session=session)

    assert targets == [
        TimeseriesTarget(
            asset_tag="PANEL-1529520",
            global_id="2QF3$F$XHF1A$PuubJ8dJ8",
            endpoint="http://localhost:8090",
            query="PANEL-1529520",
        )
    ]


def test_virtual_inverter_shell_id_passes_through_unchanged():
    session = MagicMock()
    inverter_shell_id = "https://example.org/asset-forge/aas/virtual/inverter"
    ts_id = f"{inverter_shell_id}/sm/timeseries"

    session.get.side_effect = [
        _response(json_body={"result": [_shell(inverter_shell_id, ts_id)]}),
        _response(json_body=_timeseries_elements("http://localhost:8090", "INVERTER")),
    ]

    targets = resolve_timeseries_targets("localhost", 8081, session=session)

    assert targets[0].global_id == inverter_shell_id
    assert targets[0].asset_tag == "INVERTER"


def test_shells_without_a_timeseries_submodel_are_skipped():
    session = MagicMock()
    session.get.side_effect = [
        _response(json_body={"result": [_shell("https://example.org/aas/ifc/SOME-LEAN-ELEMENT")]}),
    ]

    targets = resolve_timeseries_targets("localhost", 8081, session=session)

    assert targets == []
    assert session.get.call_count == 1  # never tries to read a non-existent timeseries submodel


def test_paginates_through_shells():
    session = MagicMock()
    panel_shell_id = "https://example.org/asset-forge/aas/ifc/GUID-1"
    ts_id = f"{panel_shell_id}/sm/timeseries"

    session.get.side_effect = [
        _response(
            json_body={
                "result": [_shell("https://example.org/aas/ifc/LEAN-1")],
                "paging_metadata": {"cursor": "next-page"},
            }
        ),
        _response(json_body={"result": [_shell(panel_shell_id, ts_id)]}),
        _response(json_body=_timeseries_elements("http://localhost:8090", "PANEL-1")),
    ]

    targets = resolve_timeseries_targets("localhost", 8081, session=session)

    assert len(targets) == 1
    assert targets[0].asset_tag == "PANEL-1"
    # 2 shell pages + 1 submodel-elements read
    assert session.get.call_count == 3


def test_incomplete_linked_segment_is_skipped():
    session = MagicMock()
    panel_shell_id = "https://example.org/asset-forge/aas/ifc/GUID-2"
    ts_id = f"{panel_shell_id}/sm/timeseries"

    session.get.side_effect = [
        _response(json_body={"result": [_shell(panel_shell_id, ts_id)]}),
        _response(json_body={"result": [{"idShort": "Segments", "value": []}]}),
    ]

    targets = resolve_timeseries_targets("localhost", 8081, session=session)

    assert targets == []
