"""Uploads/clears AAS packages against a BaSyx deployment.

Every behavior documented here (not just informed by the reference project
this pipeline's design was based on, but re-confirmed live) was exercised
against a real `eclipsebasyx/aas-environment:2.0.0-SNAPSHOT` +
`eclipsebasyx/aas-registry-log-mem:2.0.0-SNAPSHOT` pair, brought up via
`infra/docker-compose.yml` (`just basyx-up`): upload, 409-on-duplicate,
clear, descriptor registration and the `_paginated_ids` pagination shape
(`result` + `paging_metadata.cursor`) all round-tripped correctly against
the live server, not just in the mocked unit tests.

- `POST /upload` needs `Accept: application/json, */*`, or BaSyx's own JSON
  error body on a bad request comes back as a plain 406 instead of the real
  error detail.
- BaSyx does not auto-register shell/submodel descriptors in the registry,
  even with its own `REGISTRYINTEGRATION` feature env vars set on the
  server -- `upload()` re-reads the just-uploaded `.aasx` locally and POSTs
  the descriptors itself, falling back to `PUT` on a 409 (already
  registered, e.g. a re-upload).
- Every id used in a BaSyx v3 API URL path is base64url-encoded *without*
  padding.
- The registry image used here only exposes `/shell-descriptors` as a
  top-level resource -- `/submodel-descriptors` 500s ("No static resource").
  Submodel descriptors live nested inside each shell descriptor's own
  `submodelDescriptors` array on this deployment; a standalone Submodel
  Registry component would be a separate service this pipeline doesn't
  deploy. `clear()` only targets `/shell-descriptors` on the registry
  accordingly.
"""

import base64
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

import requests
from basyx.aas import model
from basyx.aas.adapter import aasx
from loguru import logger

from asset_forge.exceptions import BasyxUploadError
from asset_forge.ingestion.loader import PathLike


def _b64url(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")


def _error_detail(response: requests.Response) -> str:
    try:
        return str(response.json())
    except ValueError:
        return response.text


def _shell_descriptor(shell: model.AssetAdministrationShell, aas_env_url: str) -> Dict[str, Any]:
    submodel_descriptors = []
    for ref in shell.submodel:
        sm_id = ref.key[0].value
        submodel_descriptors.append(
            {
                "id": sm_id,
                "endpoints": [
                    {
                        "interface": "SUBMODEL-3.0",
                        "protocolInformation": {"href": f"{aas_env_url}/submodels/{_b64url(sm_id)}"},
                    }
                ],
            }
        )
    return {
        "id": shell.id,
        "idShort": shell.id_short,
        "assetKind": "Instance",
        "globalAssetId": shell.asset_information.global_asset_id,
        "endpoints": [
            {
                "interface": "AAS-3.0",
                "protocolInformation": {"href": f"{aas_env_url}/shells/{_b64url(shell.id)}"},
            }
        ],
        "submodelDescriptors": submodel_descriptors,
    }


class BasyxClient:
    def __init__(
        self,
        aas_env_host: str,
        aas_env_port: int,
        registry_host: Optional[str] = None,
        registry_port: Optional[int] = None,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.aas_env_url = f"http://{aas_env_host}:{aas_env_port}"
        self.registry_url = (
            f"http://{registry_host}:{registry_port}" if registry_host and registry_port else None
        )
        self._session = session or requests.Session()

    def upload(self, aasx_path: PathLike) -> None:
        aasx_path = Path(aasx_path)
        with open(aasx_path, "rb") as file_obj:
            response = self._session.post(
                f"{self.aas_env_url}/upload",
                files={"file": (aasx_path.name, file_obj, "application/octet-stream")},
                headers={"Accept": "application/json, */*"},
            )

        if response.status_code == 409:
            raise BasyxUploadError(f"AAS package already exists on the server: {_error_detail(response)}")
        if response.status_code not in (200, 201, 204):
            raise BasyxUploadError(f"upload failed ({response.status_code}): {response.text}")

        if self.registry_url:
            self._register_descriptors(aasx_path)

    def _register_descriptors(self, aasx_path: Path) -> None:
        store = model.DictIdentifiableStore()
        file_store = aasx.DictSupplementaryFileContainer()
        with aasx.AASXReader(str(aasx_path)) as reader:
            reader.read_into(object_store=store, file_store=file_store)

        shells = [obj for obj in store if isinstance(obj, model.AssetAdministrationShell)]
        for shell in shells:
            payload = _shell_descriptor(shell, self.aas_env_url)
            self._post_or_put_descriptor(f"{self.registry_url}/shell-descriptors", shell.id, payload)
        logger.info(f"registered {len(shells)} shell descriptor(s) with the registry")

    def _post_or_put_descriptor(self, base_url: str, id_: str, payload: Dict[str, Any]) -> None:
        response = self._session.post(base_url, json=payload)
        if response.status_code in (200, 201):
            return
        if response.status_code == 409:
            put_response = self._session.put(f"{base_url}/{_b64url(id_)}", json=payload)
            if put_response.status_code not in (200, 204):
                logger.warning(f"failed to re-register descriptor {id_!r}: {put_response.status_code}")
            return
        logger.warning(f"failed to register descriptor {id_!r}: {response.status_code} {response.text}")

    def clear(self) -> None:
        for path in ("shells", "submodels"):
            self._delete_all(f"{self.aas_env_url}/{path}")
        if self.registry_url:
            # Only shell-descriptors is a real top-level resource on the
            # `eclipsebasyx/aas-registry-log-mem` image this was tested
            # against -- confirmed live: /submodel-descriptors 500s with
            # "No static resource submodel-descriptors", since submodel
            # descriptors live nested inside each shell descriptor's own
            # submodelDescriptors array here, not a separate top-level
            # collection (that would need BaSyx's distinct Submodel
            # Registry component, not deployed by infra/docker-compose.yml).
            # Deleting the shell descriptor removes its nested ones too.
            self._delete_all(f"{self.registry_url}/shell-descriptors")

    def _delete_all(self, base_url: str) -> None:
        count = 0
        for id_ in self._paginated_ids(base_url):
            response = self._session.delete(f"{base_url}/{_b64url(id_)}")
            if response.status_code not in (200, 204):
                logger.warning(f"failed to delete {base_url}/{id_}: {response.status_code}")
            else:
                count += 1
        logger.info(f"cleared {count} item(s) from {base_url}")

    def _paginated_ids(self, base_url: str) -> Iterator[str]:
        cursor: Optional[str] = None
        while True:
            params = {"cursor": cursor} if cursor else {}
            response = self._session.get(base_url, params=params)
            if response.status_code != 200:
                logger.warning(f"failed to list {base_url}: {response.status_code}")
                return
            body = response.json()
            for item in body.get("result", []):
                yield item["id"]
            cursor = body.get("paging_metadata", {}).get("cursor")
            if not cursor:
                return
