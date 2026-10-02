import pytest
from PIL import Image

from photocull.config import QualityConfig
from photocull.hashing import PerceptualHashService, hamming
from photocull.quality import QualityAnalyzer


def metrics(photos, name):
    with Image.open(photos / name) as image:
        return QualityAnalyzer(QualityConfig()).analyze(image.convert("RGB"))


def test_quality_relative_behavior(photos):
    sharp = metrics(photos, "sharp.png")
    blurred = metrics(photos, "blurred.png")
    normal = metrics(photos, "normal.png")
    assert sharp["raw"]["laplacian_variance"] > blurred["raw"]["laplacian_variance"]
    assert sharp["normalized"]["sharpness"] > blurred["normalized"]["sharpness"]
    assert (
        metrics(photos, "bright.png")["raw"]["overexposure_fraction"]
        > normal["raw"]["overexposure_fraction"]
    )
    assert (
        metrics(photos, "dark.png")["raw"]["underexposure_fraction"]
        > normal["raw"]["underexposure_fraction"]
    )
    assert (
        metrics(photos, "high_contrast.png")["raw"]["contrast_p95_p5"]
        > metrics(photos, "low_contrast.png")["raw"]["contrast_p95_p5"]
    )
    assert (
        metrics(photos, "noisy.png")["raw"]["noise_residual_mad"]
        > normal["raw"]["noise_residual_mad"]
    )
    assert metrics(photos, "bright.png")["raw"]["luminance_high_clipping"] == 0
    assert "underexposure" in metrics(photos, "dark.png")["warnings"]
    assert "overexposure" in metrics(photos, "bright.png")["warnings"]


def test_score_components_and_determinism(photos):
    result = metrics(photos, "sharp.png")
    s = result["normalized"]
    assert result["technical_quality_v1"] == pytest.approx(
        0.4 * s["sharpness"] + 0.25 * s["exposure"] + 0.2 * s["contrast"] + 0.15 * s["resolution"]
    )
    assert result == metrics(photos, "sharp.png")
    assert all(0 <= value <= 1 for value in s.values())
    assert 0 <= result["raw"]["entropy_bits"] <= 8
    assert result["raw"]["aspect_ratio"] == 1
    assert result["raw"]["colorfulness"] == 0


def test_hashes_exact_and_transformations(photos):
    service = PerceptualHashService()

    def hashes(name):
        with Image.open(photos / name) as image:
            return service.analyze(image)

    original = hashes("sharp.png")
    assert original == hashes("exact.png")
    assert all(len(h) == 16 for h in original.values())
    # Synthetic checkerboard only: these are tolerance checks, not universal invariance.
    for name in ("resized.png", "reencoded.jpg"):
        assert hamming(original["ahash"], hashes(name)["ahash"]) <= 4
        assert hamming(original["phash"], hashes(name)["phash"]) <= 16
    assert hamming("0000000000000000", "ffffffffffffffff") == 64


def test_config_validation():
    with pytest.raises(ValueError):
        QualityConfig(sharpness_scale=0)
    with pytest.raises(ValueError):
        QualityConfig(dark_threshold=250)
    with pytest.raises(ValueError):
        QualityConfig(sharpness_weight=0.5)


def test_clipping_and_resolution(photos):
    result = metrics(photos, "sharp.png")
    assert result["raw"]["luminance_high_clipping"] == pytest.approx(0.5)
    assert result["raw"]["luminance_low_clipping"] == pytest.approx(0.5)
    assert result["raw"]["megapixels"] > metrics(photos, "resized.png")["raw"]["megapixels"]


def test_nonfinite_and_unknown_config(tmp_path):
    from photocull.config import load_config

    with pytest.raises(ValueError, match="finite"):
        QualityConfig(sharpness_scale=float("nan"))
    path = tmp_path / "invalid.toml"
    path.write_text("[quality]\nmisspelled = 4\n")
    with pytest.raises(ValueError, match="Invalid quality"):
        load_config(path)
