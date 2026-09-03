from unittest.mock import MagicMock

import pytest

from asset_forge.exceptions import BasyxUploadError
from asset_forge.integration.basyx_client import BasyxClient, _b64url


def _response(status_code=200, json_body=None, text=""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.json = MagicMock(return_value=json_body if json_body is not None else {})
    return resp


def test_b64url_has_no_padding():
    assert _b64url("https://example.org/aas/1") == _b64url("https://example.org/aas/1").rstrip("=")
    assert "=" not in _b64url("a")


def test_upload_sends_accept_header_and_octet_stream(tmp_path):
    aasx_path = tmp_path / "model.aasx"
    aasx_path.write_bytes(b"fake-zip-content")

    session = MagicMock()
    session.post.return_value = _response(200)

    client = BasyxClient(aas_env_host="localhost", aas_env_port=8081, session=session)
    client.upload(aasx_path)

    args, kwargs = session.post.call_args
    assert args[0] == "http://localhost:8081/upload"
    assert kwargs["headers"]["Accept"] == "application/json, */*"
    assert kwargs["files"]["file"][2] == "application/octet-stream"


def test_upload_raises_on_409_conflict(tmp_path):
    aasx_path = tmp_path / "model.aasx"
    aasx_path.write_bytes(b"fake-zip-content")

    session = MagicMock()
    session.post.return_value = _response(409, json_body={"messages": [{"text": "already exists"}]})

    client = BasyxClient(aas_env_host="localhost", aas_env_port=8081, session=session)

    with pytest.raises(BasyxUploadError):
        client.upload(aasx_path)


def test_upload_raises_on_unexpected_status(tmp_path):
    aasx_path = tmp_path / "model.aasx"
    aasx_path.write_bytes(b"fake-zip-content")

    session = MagicMock()
    session.post.return_value = _response(500, text="boom")

    client = BasyxClient(aas_env_host="localhost", aas_env_port=8081, session=session)

    with pytest.raises(BasyxUploadError):
        client.upload(aasx_path)


def test_upload_skips_registry_when_none_configured(tmp_path):
    aasx_path = tmp_path / "model.aasx"
    aasx_path.write_bytes(b"fake-zip-content")

    session = MagicMock()
    session.post.return_value = _response(200)

    client = BasyxClient(aas_env_host="localhost", aas_env_port=8081, session=session)
    client.upload(aasx_path)

    # only the /upload POST -- no registry calls attempted at all
    assert session.post.call_count == 1


def test_clear_paginates_and_deletes_with_base64url_ids():
    session = MagicMock()
    session.get.side_effect = [
        _response(200, json_body={"result": [{"id": "id-1"}], "paging_metadata": {"cursor": "next"}}),
        _response(200, json_body={"result": [{"id": "id-2"}], "paging_metadata": {}}),
    ]
    session.delete.return_value = _response(204)

    client = BasyxClient(aas_env_host="localhost", aas_env_port=8081, session=session)
    client._delete_all("http://localhost:8081/shells")

    deleted_urls = [call.args[0] for call in session.delete.call_args_list]
    assert deleted_urls == [
        f"http://localhost:8081/shells/{_b64url('id-1')}",
        f"http://localhost:8081/shells/{_b64url('id-2')}",
    ]


def test_clear_without_registry_only_touches_aas_env():
    session = MagicMock()
    session.get.return_value = _response(200, json_body={"result": [], "paging_metadata": {}})

    client = BasyxClient(aas_env_host="localhost", aas_env_port=8081, session=session)
    client.clear()

    called_urls = [call.args[0] for call in session.get.call_args_list]
    assert called_urls == ["http://localhost:8081/shells", "http://localhost:8081/submodels"]


def test_clear_with_registry_only_touches_shell_descriptors_not_submodel_descriptors():
    # Confirmed live against eclipsebasyx/aas-registry-log-mem:2.0.0-SNAPSHOT:
    # /submodel-descriptors is not a real endpoint on that image (500s with
    # "No static resource") -- submodel descriptors live nested inside each
    # shell descriptor there instead.
    session = MagicMock()
    session.get.return_value = _response(200, json_body={"result": [], "paging_metadata": {}})

    client = BasyxClient(
        aas_env_host="localhost", aas_env_port=8081, registry_host="localhost", registry_port=8082, session=session
    )
    client.clear()

    called_urls = [call.args[0] for call in session.get.call_args_list]
    assert called_urls == [
        "http://localhost:8081/shells",
        "http://localhost:8081/submodels",
        "http://localhost:8082/shell-descriptors",
    ]


def test_post_or_put_descriptor_falls_back_to_put_on_409():
    session = MagicMock()
    session.post.return_value = _response(409)
    session.put.return_value = _response(204)

    client = BasyxClient(
        aas_env_host="localhost", aas_env_port=8081, registry_host="localhost", registry_port=8082, session=session
    )
    client._post_or_put_descriptor("http://localhost:8082/shell-descriptors", "shell-1", {"id": "shell-1"})

    session.put.assert_called_once()
    put_url = session.put.call_args.args[0]
    assert put_url == f"http://localhost:8082/shell-descriptors/{_b64url('shell-1')}"
