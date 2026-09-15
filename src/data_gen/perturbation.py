"""Per-panel perturbation profiles for the simulated plant.

A profile is a small, seed-reproducible per-panel adjustment
(``irradiance_factor``, ``temperature_offset``) applied on top of the shared
base irradiance/temperature series (see ``send_data_to_OPCUA.py``'s
dataset), so panels don't all report identical sensor readings. Deliberate
per-panel deviations (e.g. to exercise alarm/anomaly-detection logic) are
layered on top via :func:`apply_anomaly`, independent of the random
perturbation.
"""

from __future__ import annotations

from typing import Literal, Sequence

import numpy as np
import pandas as pd

PROFILE_COLUMNS = ("panel_tag", "irradiance_factor", "temperature_offset", "seed")


def generate_profiles(
    panel_tags: Sequence[str],
    mode: Literal["uniform", "perturbed"] = "uniform",
    seed: int | None = None,
    irradiance_noise_std: float = 0.05,
    temperature_noise_std: float = 1.0,
) -> pd.DataFrame:
    """Generate one perturbation profile per panel tag.

    ``mode="uniform"``: every panel gets ``irradiance_factor=1.0`` and
    ``temperature_offset=0.0`` -- the base series is used unmodified for
    every panel.

    ``mode="perturbed"``: each panel's ``irradiance_factor`` is drawn from
    ``1 + N(0, irradiance_noise_std)`` (clipped to be non-negative) and
    ``temperature_offset`` from ``N(0, temperature_noise_std)``, using
    ``numpy.random.default_rng(seed)`` for reproducibility.

    Args:
        panel_tags: Asset tags to generate a profile for, one row per tag
            (e.g. ``["PANEL-1529520", "PANEL-1529522"]``), in the given
            order.
        mode: ``"uniform"`` for a neutral profile, ``"perturbed"`` to draw
            random per-panel values.
        seed: Seed for ``numpy.random.default_rng``. Ignored when
            ``mode="uniform"``. ``None`` draws non-reproducible randomness.
        irradiance_noise_std: Standard deviation of the irradiance factor's
            noise term, as a fraction of the base irradiance (e.g. ``0.05``
            = 5%). Only used when ``mode="perturbed"``.
        temperature_noise_std: Standard deviation of the temperature
            offset's noise term, in °C. Only used when ``mode="perturbed"``.

    Returns:
        A DataFrame with columns ``panel_tag``, ``irradiance_factor``,
        ``temperature_offset``, ``seed`` -- one row per entry in
        ``panel_tags``, in the same order.

    Raises:
        ValueError: If ``mode`` is neither ``"uniform"`` nor ``"perturbed"``.
    """
    panel_tags = list(panel_tags)

    if mode == "uniform":
        irradiance_factor = np.ones(len(panel_tags))
        temperature_offset = np.zeros(len(panel_tags))
    elif mode == "perturbed":
        rng = np.random.default_rng(seed)
        irradiance_factor = np.clip(
            1.0 + rng.normal(0.0, irradiance_noise_std, size=len(panel_tags)), 0.0, None
        )
        temperature_offset = rng.normal(0.0, temperature_noise_std, size=len(panel_tags))
    else:
        raise ValueError(f"unknown mode: {mode!r}")

    return pd.DataFrame(
        {
            "panel_tag": panel_tags,
            "irradiance_factor": irradiance_factor,
            "temperature_offset": temperature_offset,
            "seed": seed,
        },
        columns=PROFILE_COLUMNS,
    )


def apply_anomaly(
    profiles: pd.DataFrame,
    panel_tags: Sequence[str],
    irradiance_factor: float | None = None,
    temperature_offset: float | None = None,
) -> pd.DataFrame:
    """Return a copy of ``profiles`` with the given panels' fields overridden.

    Args:
        profiles: A profile table as returned by :func:`generate_profiles`
            (must have a ``panel_tag`` column).
        panel_tags: Which panels' rows to override.
        irradiance_factor: New ``irradiance_factor`` for the given panels.
            Left unchanged when ``None``.
        temperature_offset: New ``temperature_offset`` for the given panels.
            Left unchanged when ``None``.

    Returns:
        A new DataFrame (``profiles`` is not modified in place) with the
        given panels' fields overridden; every other row is untouched.

    Raises:
        ValueError: If any entry in ``panel_tags`` isn't present in
            ``profiles["panel_tag"]`` -- catches a typo'd tag rather than
            silently doing nothing.
    """
    panel_tags = list(panel_tags)
    known_tags = set(profiles["panel_tag"])
    unknown = [tag for tag in panel_tags if tag not in known_tags]
    if unknown:
        raise ValueError(f"unknown panel_tag(s): {unknown}")

    result = profiles.copy()
    mask = result["panel_tag"].isin(panel_tags)
    if irradiance_factor is not None:
        result.loc[mask, "irradiance_factor"] = irradiance_factor
    if temperature_offset is not None:
        result.loc[mask, "temperature_offset"] = temperature_offset
    return result
