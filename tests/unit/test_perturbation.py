import sys
from pathlib import Path

import pandas.testing as pdt
import pytest

sys.path.append(str(Path(__file__).resolve().parent.parent.parent / "src" / "data_gen"))

from perturbation import apply_anomaly, generate_profiles


def test_uniform_mode_is_neutral():
    profiles = generate_profiles(["PANEL-1", "PANEL-2"], mode="uniform")

    assert (profiles["irradiance_factor"] == 1.0).all()
    assert (profiles["temperature_offset"] == 0.0).all()


def test_uniform_mode_covers_every_panel_tag():
    tags = ["PANEL-1", "PANEL-2", "PANEL-3"]
    profiles = generate_profiles(tags, mode="uniform")

    assert list(profiles["panel_tag"]) == tags


def test_perturbed_mode_is_reproducible_with_the_same_seed():
    tags = [f"PANEL-{i}" for i in range(20)]
    first = generate_profiles(tags, mode="perturbed", seed=42)
    second = generate_profiles(tags, mode="perturbed", seed=42)

    pdt.assert_frame_equal(first, second)


def test_perturbed_mode_differs_across_seeds():
    tags = [f"PANEL-{i}" for i in range(20)]
    first = generate_profiles(tags, mode="perturbed", seed=1)
    second = generate_profiles(tags, mode="perturbed", seed=2)

    assert not first["irradiance_factor"].equals(second["irradiance_factor"])


def test_perturbed_irradiance_factor_is_never_negative():
    tags = [f"PANEL-{i}" for i in range(200)]
    # Large noise std to make clipping likely to matter.
    profiles = generate_profiles(tags, mode="perturbed", seed=0, irradiance_noise_std=5.0)

    assert (profiles["irradiance_factor"] >= 0.0).all()


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError):
        generate_profiles(["PANEL-1"], mode="not-a-mode")


def test_apply_anomaly_only_changes_the_given_panels():
    profiles = generate_profiles(["PANEL-1", "PANEL-2", "PANEL-3"], mode="uniform")

    result = apply_anomaly(profiles, ["PANEL-2"], irradiance_factor=0.2)

    changed = result.set_index("panel_tag")
    assert changed.loc["PANEL-2", "irradiance_factor"] == 0.2
    assert changed.loc["PANEL-1", "irradiance_factor"] == 1.0
    assert changed.loc["PANEL-3", "irradiance_factor"] == 1.0


def test_apply_anomaly_only_overrides_the_given_fields():
    profiles = generate_profiles(["PANEL-1"], mode="uniform")

    result = apply_anomaly(profiles, ["PANEL-1"], temperature_offset=15.0)

    row = result.set_index("panel_tag").loc["PANEL-1"]
    assert row["temperature_offset"] == 15.0
    assert row["irradiance_factor"] == 1.0  # untouched


def test_apply_anomaly_does_not_mutate_the_input():
    profiles = generate_profiles(["PANEL-1"], mode="uniform")

    apply_anomaly(profiles, ["PANEL-1"], irradiance_factor=0.1)

    assert profiles.set_index("panel_tag").loc["PANEL-1", "irradiance_factor"] == 1.0


def test_apply_anomaly_rejects_unknown_panel_tag():
    profiles = generate_profiles(["PANEL-1"], mode="uniform")

    with pytest.raises(ValueError):
        apply_anomaly(profiles, ["PANEL-DOES-NOT-EXIST"], irradiance_factor=0.1)
