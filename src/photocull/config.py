"""Versioned configuration; canonical hashes invalidate derived results."""

import hashlib
import json
import math
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path


def parameter_hash(value: dict) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode()).hexdigest()


@dataclass(frozen=True)
class QualityConfig:
    analysis_edge: int = 1024
    sharpness_scale: float = 500.0
    exposure_target: float = 0.5
    exposure_tolerance: float = 0.5
    dark_threshold: int = 16
    bright_threshold: int = 240
    clipping_low: int = 1
    clipping_high: int = 254
    resolution_target_mp: float = 12.0
    blur_warning_score: float = 0.15
    exposure_warning_fraction: float = 0.25
    low_resolution_mp: float = 1.0
    noise_gradient_limit: float = 10.0
    noise_sigma: float = 1.0
    sharpness_weight: float = 0.40
    exposure_weight: float = 0.25
    contrast_weight: float = 0.20
    resolution_weight: float = 0.15

    def __post_init__(self):
        if not all(math.isfinite(value) for value in asdict(self).values()):
            raise ValueError("Quality parameters must be finite")
        if not 64 <= self.analysis_edge <= 4096:
            raise ValueError("analysis_edge must be between 64 and 4096")
        if (
            min(
                self.sharpness_scale,
                self.resolution_target_mp,
                self.exposure_tolerance,
                self.noise_sigma,
            )
            <= 0
        ):
            raise ValueError("Quality scales must be positive")
        if (
            not 0
            <= self.clipping_low
            < self.dark_threshold
            < self.bright_threshold
            < self.clipping_high
            <= 255
        ):
            raise ValueError("Luminance thresholds must be ordered within 0..255")
        if not 0 <= self.exposure_target <= 1 or self.noise_gradient_limit < 0:
            raise ValueError("Invalid exposure target or gradient limit")
        if any(not 0 <= x <= 1 for x in (self.blur_warning_score, self.exposure_warning_fraction)):
            raise ValueError("Warning thresholds must be within 0..1")
        weights = (
            self.sharpness_weight,
            self.exposure_weight,
            self.contrast_weight,
            self.resolution_weight,
        )
        if min(weights) < 0 or abs(sum(weights) - 1) > 1e-9:
            raise ValueError("Quality weights must be nonnegative and sum to 1")
        if weights != (0.4, 0.25, 0.2, 0.15):
            raise ValueError("technical_quality_v1 has fixed approved weights")


@dataclass(frozen=True)
class DuplicateConfig:
    phash_distance: int = 2
    dhash_distance: int = 8
    ahash_distance: int = 8
    aspect_log_difference: float = 0.04
    min_entropy: float = 3.0
    min_contrast: float = 25.0
    verification_correlation: float = 0.999
    chroma_difference: float = 0.12
    near_capture_window: float = 60.0
    burst_window: float = 5.0
    burst_phash_distance: int = 12
    burst_dhash_distance: int = 18
    burst_ahash_distance: int = 16
    burst_correlation: float = 0.70
    burst_aspect_log_difference: float = 0.15
    allow_filesystem_bursts: bool = False
    max_candidates_per_photo: int = 256
    max_comparisons: int = 100000
    max_group_members: int = 128

    def __post_init__(self):
        if not all(math.isfinite(v) for v in asdict(self).values()):
            raise ValueError("Duplicate parameters must be finite")
        if any(
            not isinstance(v, int) or not 0 <= v <= 64
            for v in (
                self.phash_distance,
                self.dhash_distance,
                self.ahash_distance,
                self.burst_phash_distance,
                self.burst_dhash_distance,
                self.burst_ahash_distance,
            )
        ):
            raise ValueError("Hash distances must be integers within 0..64")
        if not 0 <= self.verification_correlation <= 1 or not 0 <= self.burst_correlation <= 1:
            raise ValueError("Correlation thresholds must be within 0..1")
        if (
            min(
                self.near_capture_window,
                self.burst_window,
                self.max_candidates_per_photo,
                self.max_comparisons,
                self.max_group_members,
            )
            <= 0
        ):
            raise ValueError("Windows and work limits must be positive")
        if any(
            type(v) is not int
            for v in (self.max_candidates_per_photo, self.max_comparisons, self.max_group_members)
        ):
            raise ValueError("Work limits must be integers")
        if type(self.allow_filesystem_bursts) is not bool:
            raise ValueError("allow_filesystem_bursts must be boolean")
        if (
            min(
                self.aspect_log_difference,
                self.min_entropy,
                self.min_contrast,
                self.chroma_difference,
                self.burst_aspect_log_difference,
            )
            < 0
        ):
            raise ValueError("Duplicate thresholds must be nonnegative")


@dataclass(frozen=True)
class EmbeddingConfig:
    model: str = "disabled"
    device: str = "cpu"
    batch_size: int = 16
    cosine_threshold: float = 0.95
    recovery_enabled: bool = True
    retrieval_neighbors: int = 16
    retrieval_probes: int = 8
    moderate_phash: int = 8
    corroborating_hash: int = 16
    pixel_floor: float = 0.90
    aspect_limit: float = 0.04

    def __post_init__(self):
        if type(self.recovery_enabled) is not bool:
            raise ValueError("recovery_enabled must be boolean")
        if self.model not in {"disabled", "mobilenet", "tinyclip"}:
            raise ValueError("Unknown embedding model")
        if self.device not in {"cpu", "mps", "auto"}:
            raise ValueError("Unknown inference device")
        if (
            any(
                type(v) is not int or v < 1
                for v in (self.batch_size, self.retrieval_neighbors, self.retrieval_probes)
            )
            or self.batch_size > 256
            or self.retrieval_neighbors > 64
            or self.retrieval_probes > 32
        ):
            raise ValueError("Invalid embedding work limits")
        if any(
            type(v) is not int or not 0 <= v <= 64
            for v in (self.moderate_phash, self.corroborating_hash)
        ):
            raise ValueError("Invalid hybrid hash limits")
        if any(
            not math.isfinite(v) or not 0 <= v <= 1
            for v in (self.cosine_threshold, self.pixel_floor, self.aspect_limit)
        ):
            raise ValueError("Invalid hybrid thresholds")


@dataclass(frozen=True)
class EventConfig:
    method: str = "time"
    model: str = "disabled"
    gap_minutes: float = 120.0
    coarse_gap_minutes: float = 240.0
    max_span_hours: float = 18.0
    time_weight: float = 0.3
    visual_weight: float = 0.7
    epsilon: float = 0.25
    min_samples: int = 2
    candidate_neighbors: int = 64
    hdbscan_window_limit: int = 256
    pure_visual: bool = False

    def __post_init__(self):
        if self.method not in {"time", "dbscan", "hdbscan"}:
            raise ValueError("Unknown event method")
        if self.model not in {"disabled", "mobilenet", "tinyclip"}:
            raise ValueError("Unknown event model")
        if self.method != "time" and self.model == "disabled":
            raise ValueError("Visual clustering requires a local model")
        if type(self.pure_visual) is not bool:
            raise ValueError("pure_visual must be boolean")
        values = (
            self.gap_minutes,
            self.coarse_gap_minutes,
            self.max_span_hours,
            self.time_weight,
            self.visual_weight,
            self.epsilon,
        )
        if not all(math.isfinite(v) for v in values):
            raise ValueError("Event parameters must be finite")
        if (
            min(self.gap_minutes, self.coarse_gap_minutes, self.max_span_hours, self.epsilon) <= 0
            or self.max_span_hours > 24
        ):
            raise ValueError("Event windows must be positive and span at most 24 hours")
        if (
            min(self.time_weight, self.visual_weight) < 0
            or abs(self.time_weight + self.visual_weight - 1) > 1e-9
        ):
            raise ValueError("Event distance weights must sum to one")
        for value, limit in (
            (self.min_samples, 64),
            (self.candidate_neighbors, 256),
            (self.hdbscan_window_limit, 512),
        ):
            if type(value) is not int or not 1 <= value <= limit:
                raise ValueError("Invalid event work limit")


@dataclass(frozen=True)
class RankingConfig:
    variant: str = "B"
    model: str = "disabled"
    quality_weight: float = 0.60
    representation_weight: float = 0.35
    uniqueness_weight: float = 0.05
    uniqueness_cap: float = 0.10
    diversity_penalty: float = 0.25
    coverage_bonus: float = 0.05
    quality_floor: float = 0.20
    neighbor_limit: int = 32
    burst_quality_weight: float = 0.70

    def __post_init__(self):
        if self.variant not in {"A", "B"} or self.model not in {
            "disabled",
            "mobilenet",
            "tinyclip",
        }:
            raise ValueError("Unknown ranking variant/model; personalization is not supported")
        weights = (self.quality_weight, self.representation_weight, self.uniqueness_weight)
        if abs(sum(weights) - 1) > 1e-9:
            raise ValueError("Ranking weights must sum to one")
        if any(
            not math.isfinite(v) or not 0 <= v <= 1
            for v in (
                *weights,
                self.uniqueness_cap,
                self.diversity_penalty,
                self.coverage_bonus,
                self.quality_floor,
                self.burst_quality_weight,
            )
        ):
            raise ValueError("Ranking parameters must be finite within 0..1")
        if type(self.neighbor_limit) is not int or not 1 <= self.neighbor_limit <= 128:
            raise ValueError("Invalid ranking neighbor limit")


@dataclass(frozen=True)
class Config:
    cache_dir: Path = field(default_factory=lambda: Path.home() / ".photocull")
    thumbnail_edge: int = 512
    thumbnail_quality: int = 85
    max_pixels: int = 80_000_000
    quality: QualityConfig = field(default_factory=QualityConfig)
    duplicates: DuplicateConfig = field(default_factory=DuplicateConfig)
    embeddings: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    events: EventConfig = field(default_factory=EventConfig)
    ranking: RankingConfig = field(default_factory=RankingConfig)

    def __post_init__(self):
        if not 64 <= self.thumbnail_edge <= 2048 or not 1 <= self.thumbnail_quality <= 95:
            raise ValueError("Invalid thumbnail configuration")
        if not 1 <= self.max_pixels <= 200_000_000:
            raise ValueError("max_pixels must be within 1..200000000")

    def snapshot(self) -> dict:
        result = asdict(self)
        result["cache_dir"] = str(self.cache_dir.absolute())
        return result

    @classmethod
    def from_snapshot(cls, data: dict):
        return cls(
            **{
                **data,
                "cache_dir": Path(data["cache_dir"]),
                "quality": QualityConfig(**data["quality"]),
                "duplicates": DuplicateConfig(**data.get("duplicates", {})),
                "embeddings": EmbeddingConfig(**data.get("embeddings", {})),
                "events": EventConfig(**data.get("events", {})),
                "ranking": RankingConfig(**data.get("ranking", {})),
            }
        )


def load_config(path: Path | None = None, cache_dir: Path | None = None) -> Config:
    data = tomllib.loads(path.read_text()) if path else {}
    try:
        quality = QualityConfig(**data.pop("quality", {}))
        duplicates = DuplicateConfig(**data.pop("duplicates", {}))
        embeddings = EmbeddingConfig(**data.pop("embeddings", {}))
        events = EventConfig(**data.pop("events", {}))
        ranking = RankingConfig(**data.pop("ranking", {}))
    except TypeError as exc:
        raise ValueError(f"Invalid quality configuration: {exc}") from exc
    if "cache_dir" in data:
        data["cache_dir"] = Path(data["cache_dir"]).expanduser()
    if cache_dir is not None:
        data["cache_dir"] = cache_dir.expanduser()
    try:
        return Config(
            **data,
            quality=quality,
            duplicates=duplicates,
            embeddings=embeddings,
            events=events,
            ranking=ranking,
        )
    except TypeError as exc:
        raise ValueError(f"Invalid application configuration: {exc}") from exc
