"""Technical indicators, not an aesthetic assessment."""

from dataclasses import asdict

import cv2
import numpy as np
from PIL import Image

from photocull.config import QualityConfig
from photocull.provenance import image_runtime


class QualityAnalyzer:
    name = "QualityAnalyzer"
    version = "technical_quality_v1"

    def __init__(self, config: QualityConfig):
        self.config = config

    @property
    def parameters(self):
        return {**asdict(self.config), "runtime": image_runtime()}

    def analyze(self, image: Image.Image, source_size=None) -> dict:
        c = self.config
        small = image.copy()
        small.thumbnail((c.analysis_edge, c.analysis_edge), Image.Resampling.LANCZOS)
        rgb = np.asarray(small, dtype=np.float32)
        small.close()
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        sharpness = float(cv2.Laplacian(gray, cv2.CV_32F).var())
        mean = float(gray.mean() / 255)
        under = float(np.mean(gray < c.dark_threshold))
        over = float(np.mean(gray > c.bright_threshold))
        clipping_low = float(np.mean(gray <= c.clipping_low))
        clipping_high = float(np.mean(gray >= c.clipping_high))
        channel_low = float(np.mean(rgb <= c.clipping_low))
        channel_high = float(np.mean(rgb >= c.clipping_high))
        contrast = float(np.percentile(gray, 95) - np.percentile(gray, 5))
        histogram = np.histogram(gray, bins=256, range=(0, 256))[0].astype(float)
        probabilities = histogram[histogram > 0] / histogram.sum()
        entropy = float(-np.sum(probabilities * np.log2(probabilities)))
        smooth = cv2.GaussianBlur(gray, (0, 0), c.noise_sigma)
        gradient = np.hypot(
            cv2.Sobel(smooth, cv2.CV_32F, 1, 0), cv2.Sobel(smooth, cv2.CV_32F, 0, 1)
        )
        residual = (gray - smooth)[gradient < c.noise_gradient_limit]
        noise = float(np.median(np.abs(residual - np.median(residual)))) if residual.size else 0.0
        rg = rgb[:, :, 0] - rgb[:, :, 1]
        yb = 0.5 * (rgb[:, :, 0] + rgb[:, :, 1]) - rgb[:, :, 2]
        colorfulness = float(np.hypot(rg.std(), yb.std()) + 0.3 * np.hypot(rg.mean(), yb.mean()))
        source_width, source_height = source_size or image.size
        mp = source_width * source_height / 1e6
        scores = {
            "sharpness": sharpness / (sharpness + c.sharpness_scale),
            "exposure": float(
                np.clip(1 - abs(mean - c.exposure_target) / c.exposure_tolerance, 0, 1)
            ),
            "contrast": contrast / 255,
            "resolution": min(mp / c.resolution_target_mp, 1.0),
        }
        score = (
            c.sharpness_weight * scores["sharpness"]
            + c.exposure_weight * scores["exposure"]
            + c.contrast_weight * scores["contrast"]
            + c.resolution_weight * scores["resolution"]
        )
        warnings = []
        if scores["sharpness"] < c.blur_warning_score:
            warnings.append("low_sharpness")
        if under > c.exposure_warning_fraction:
            warnings.append("underexposure")
        if over > c.exposure_warning_fraction:
            warnings.append("overexposure")
        if mp < c.low_resolution_mp:
            warnings.append("low_resolution")
        return {
            "raw": {
                "laplacian_variance": sharpness,
                "mean_luminance": mean,
                "underexposure_fraction": under,
                "overexposure_fraction": over,
                "luminance_low_clipping": clipping_low,
                "luminance_high_clipping": clipping_high,
                "channel_low_clipping": channel_low,
                "channel_high_clipping": channel_high,
                "contrast_p95_p5": contrast,
                "megapixels": mp,
                "aspect_ratio": source_width / source_height,
                "entropy_bits": entropy,
                "noise_residual_mad": noise,
                "colorfulness": colorfulness,
                "analysis_width": small.width,
                "analysis_height": small.height,
            },
            "normalized": scores,
            "technical_quality_v1": score,
            "warnings": warnings,
        }
