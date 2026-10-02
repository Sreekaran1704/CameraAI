# Technical Quality v1 / Version A

Inputs are EXIF-orientation-corrected RGB. Quality analysis downsamples without upscaling to a
maximum edge of 1024 using Lanczos. Resolution/aspect ratio use full oriented dimensions.
OpenCV RGB-to-grayscale luminance uses its standard RGB weights, with values on 0..255.
Raw measurements and normalized components are separate JSON fields in SQLite.

| Raw indicator | Definition | Interpretation limits |
| --- | --- | --- |
| laplacian_variance | Variance of OpenCV 3×3-neighborhood Laplacian with default ksize=1, float32. | Noise and texture can appear sharp; scale matters. |
| mean_luminance | Mean grayscale / 255. | Brightness is scene-dependent. |
| underexposure_fraction | Fraction grayscale <16. | Intentional shadows may trigger a warning. |
| overexposure_fraction | Fraction grayscale >240. | Intentional highlights may trigger a warning. |
| luminance_low/high_clipping | Fractions grayscale ≤1 / ≥254. | Proxy for endpoint clipping. |
| channel_low/high_clipping | Fractions of all RGB channel samples ≤1 / ≥254. | Can flag saturated colors without luminance clipping. |
| contrast_p95_p5 | 95th minus 5th grayscale percentile. | Low-contrast scenes may be intentional. |
| megapixels | Oriented width × height / 1,000,000. | Does not measure detail or effective resolution. |
| aspect_ratio | Oriented width / height. | Descriptive only. |
| entropy_bits | Shannon entropy of 256-bin grayscale histogram. | Minimal compositions can have low entropy. |
| noise_residual_mad | Median absolute deviation around median of grayscale minus Gaussian-smoothed grayscale; samples restricted to smooth-image Sobel magnitude <10. | Texture/JPEG artifacts confound it; 0 also means no eligible samples. |
| colorfulness | sqrt(var(R−G)+var((R+G)/2−B)) + .3 × sqrt(mean(R−G)²+mean((R+G)/2−B)²). | Descriptive, no color preference assumed. |

Gaussian smoothing uses sigma=1 and automatically selected kernel size. `analysis_width` and
`analysis_height` record the actual measurement scale. Contrast percentiles use NumPy defaults.

Normalized components, each on 0..1:

```text
S = laplacian_variance / (laplacian_variance + 500)
E = clip(1 − abs(mean_luminance − 0.5) / 0.5, 0, 1)
C = contrast_p95_p5 / 255
R = min(megapixels / 12, 1)
technical_quality_v1 = 0.40 S + 0.25 E + 0.20 C + 0.15 R
```

Warnings: S<.15 → low_sharpness; under/overexposure fraction>.25 → respective exposure warning;
megapixels<1 → low_resolution. Comparisons are strictly < or > as specified. These are provisional
technical thresholds, not calibrated photographic accuracy. All thresholds/scales are centralized
in QualityConfig and configurable through TOML. Approved Version A weights are fixed; new weights
need a new scoring version rather than silently redefining `technical_quality_v1`.

Entropy, noise, clipping, aspect ratio and colorfulness do not independently reduce the score.
Every persisted result links to source fingerprint, analyzer name, algorithm version, canonical
parameter hash (including library versions), and generated UTC time. Changing thresholds
invalidates quality outputs without invalidating otherwise compatible hashes/thumbnails.
