"""Downloads/caches official IDTA AAS submodel templates.

Templates are fetched once from the official `admin-shell-io/submodel-templates`
GitHub repository (public specification artifacts -- the URLs are IDTA's own,
not anything project-specific) and cached under `data/submodels/` so repeat
runs and tests never need network access.

Two known issues in the raw template JSON are fixed on load, both confirmed
against a live BaSyx aas-environment:

- A `Blob` with a literal JSON `null` value (e.g. the OPC UA template's
  `ServerCertificate`) must become `b""`, or BaSyx's XML serializer emits a
  self-closing tag that stricter viewers reject.
- The template's own `kind=TEMPLATE` / `administration` version metadata must
  be cleared to `kind=INSTANCE` / no administration, since what gets
  uploaded is one real asset's instance data, not the abstract template
  document (left as TEMPLATE, viewers label it e.g. "<T> Nameplate V3.0").
"""

import copy
import io
import re
import urllib.request
from pathlib import Path
from typing import Dict

from basyx.aas import model
from basyx.aas.adapter.json import read_aas_json_file
from loguru import logger

from asset_forge.config import SUBMODEL_TEMPLATE_CACHE_DIR

_parsed_template_cache: Dict[str, model.Submodel] = {}

TEMPLATE_URLS: Dict[str, str] = {
    "nameplate": (
        "https://raw.githubusercontent.com/admin-shell-io/submodel-templates/"
        "refs/heads/main/published/Digital%20nameplate/3/0/1/"
        "IDTA%2002006-3-0-1_Template_Digital%20Nameplate.json"
    ),
    "technicaldata": (
        "https://raw.githubusercontent.com/admin-shell-io/submodel-templates/"
        "refs/heads/main/published/Technical_Data/2/0/1/"
        "IDTA%2002003_2-0-1_Template_TechnicalData_forAASMetamodelV3.1.json"
    ),
    "opcua": (
        "https://raw.githubusercontent.com/admin-shell-io/submodel-templates/"
        "refs/heads/main/published/OPC%20UA%20Server%20Datasheet/1/0/"
        "IDTA%2002009-1-0-Template-OPCUA-Server%20Datasheet.json"
    ),
    "timeseries": (
        "https://raw.githubusercontent.com/admin-shell-io/submodel-templates/"
        "refs/heads/main/published/Time%20Series%20Data/1/1/1/"
        "IDTA%2002008-1-1-1_Template_TimeSeriesData_forAASMetamodelV3.1.json"
    ),
}


def _cache_filename(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") + ".json"


def _fetch(name: str) -> bytes:
    cache_path = SUBMODEL_TEMPLATE_CACHE_DIR / _cache_filename(name)
    if cache_path.is_file():
        return cache_path.read_bytes()

    url = TEMPLATE_URLS[name]
    logger.info(f"downloading IDTA submodel template '{name}' from {url}")
    with urllib.request.urlopen(url, timeout=10) as response:  # noqa: S310 (fixed, https, IDTA's own URL)
        data = response.read()

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(data)
    return data


def _fix_null_blobs(element) -> None:
    if isinstance(element, model.Blob) and element.value is None:
        element.value = b""
        return
    if isinstance(element, model.SubmodelElementCollection):
        for child in element.value:
            _fix_null_blobs(child)
    elif isinstance(element, model.SubmodelElementList):
        for child in element.value:
            _fix_null_blobs(child)


def _parse_template(name: str) -> model.Submodel:
    raw = _fetch(name)
    store = read_aas_json_file(io.BytesIO(raw))
    submodels = [obj for obj in store if isinstance(obj, model.Submodel)]
    if not submodels:
        raise ValueError(f"template {name!r} contains no Submodel")
    submodel = submodels[0]

    submodel.kind = model.ModellingKind.INSTANCE
    submodel.administration = None
    for element in submodel.submodel_element:
        _fix_null_blobs(element)

    return submodel


def load_template(name: str) -> model.Submodel:
    """Return a fresh, instance-ready copy of the named IDTA submodel
    template (see TEMPLATE_URLS for the available names).

    The parsed-and-fixed Submodel is cached in-process per name after its
    first parse, so a plant with thousands of elements (calling this once
    or twice per element) only pays basyx's JSON deserialization cost once
    per template, not once per element -- every call after the first just
    deep-copies the cached object. Profiled against a 200-element subset of
    a real MEP discipline file: deep-copying the *full* template (including
    the large example-content lists like TechnicalPropertyAreas, which
    submodels.py immediately clears anyway) was still a measurable chunk of
    total time, comparable to basyx's own AASX JSON writer -- if this ever
    needs to be faster for a much larger plant, clearing those same unused
    example lists on the *cached* template before caching it (once) rather
    than after every deep-copy (once per element) is the next thing to try.
    """
    if name not in TEMPLATE_URLS:
        raise ValueError(f"unknown submodel template {name!r}; known: {sorted(TEMPLATE_URLS)}")

    if name not in _parsed_template_cache:
        _parsed_template_cache[name] = _parse_template(name)

    return copy.deepcopy(_parsed_template_cache[name])
