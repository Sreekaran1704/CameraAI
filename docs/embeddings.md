# Local embeddings and hybrid similarity

Phase 3 is an experiment. Hash-only remains the default because both tested hybrid models fell
below the precision target on the expanded hard benchmark. The UI's optional models are labeled
experimental. They never perform remote inference or download during a scan.

## Installation and explicit setup

Install the optional environment and download only the model you intend to evaluate:

    .venv/bin/python -m pip install -e '.[embeddings]'
    .venv/bin/photocull --cache-dir .photocull model-setup mobilenet
    .venv/bin/photocull --cache-dir .photocull model-setup tinyclip

Setup uses verified HTTPS with the system certificate store. Both registered checkpoints have
pinned full SHA-256 checksums; publication is atomic under the cache lock. Loading uses tensor-only
PyTorch deserialization. No scan calls setup or passes a remote pretrained identifier.
Missing, unrecognized or unreadable weights fall back to Phase 2 and expose a setup instruction.

## Model registry

| Model | Features | Dimensions | Download bytes | Preprocessing |
| --- | --- | ---: | ---: | --- |
| MobileNetV3 Small, ImageNet1K V1 | Pooled features before classifier | 576 | 10,306,551 | EXIF RGB, short edge 256 bilinear, center 224, ImageNet mean/std |
| TinyCLIP ViT-8M/16 Text-3M, YFCC15M | Projected image encoder output | 512 | 46,948,845 | EXIF RGB, short edge 224 bicubic, center 224, CLIP mean/std |

MobileNet loads through torchvision. TinyCLIP's author-specified 10-layer, width-256 ViT
configuration loads into OpenCLIP's public CLIP class. Only the image encoder remains for
inference. Both use float32, evaluation mode, inference-only execution and L2 normalization.
CPU is the default. Explicit MPS/auto selection checks availability and falls back to CPU for
unsupported device execution; real benchmarks validate CPU only.

The [torchvision model documentation](https://docs.pytorch.org/vision/main/models/generated/torchvision.models.mobilenet_v3_small.html)
describes the MobileNet checkpoint/preprocessing. Torchvision code is BSD-3-Clause; ImageNet
data terms are separate. [TinyCLIP's model card](https://huggingface.co/wkcn/TinyCLIP-ViT-8M-16-Text-3M-YFCC15M)
identifies the checkpoint as MIT, with the [author's architecture](https://github.com/wkcn/TinyCLIP/blob/main/src/open_clip/model_configs/TinyCLIP-ViT-8M-16-Text-3M.json)
and [license](https://github.com/wkcn/TinyCLIP/blob/main/LICENSE). Dataset/photo rights remain
separate from code/model licenses.

MobileCLIP-S1 was considered and downloaded during model research, then excluded after checking
its [research-only weight license](https://huggingface.co/apple/MobileCLIP-S1-OpenCLIP/blob/main/LICENSE).
It is absent from the final registry and runtime settings. Its ignored local research artifact
is not a PhotoCull runtime dependency.

## Cache and provenance

The application-owned embeddings directory contains float32 NPY vectors with no image bytes.
Identity includes source fingerprint, model ID, full checksum, preprocessing version, service
version, relevant numerical/library versions and requested device. Each output validates shape,
finiteness and unit norm; invalid cached vectors regenerate. Atomic files use private temporary
file permissions. Schema 3 adds embedding_records with source/model/preprocessing identity,
analysis-version reference, path, dimensions, device and generation time.

Derived clearing removes vectors and metadata, preserves local model weights and human
corrections, and invalidates automatic groups. The embedding vectors are derived private data;
they are not anonymous merely because they are not pixels. Existing disk-encryption/cache
privacy limitations still apply.

## Explainable hybrid rule

near_duplicate_v2 preserves every Phase 2 near decision. A recovery requires all of:

- Cosine at least 0.95.
- pHash at most 8; dHash and aHash each at most 16.
- Phase 2 entropy/contrast guards and chroma difference at most 0.12.
- Gray thumbnail correlation at least 0.90 and log-aspect difference at most 0.04.
- Comparable reliable EXIF times must be equal for a recovery. Distinct captured frames remain
  burst candidates; unknown/incomparable capture times do not establish temporal agreement.

These are development-selected experimental thresholds, not calibrated probabilities. None
overrides an existing Not Duplicate correction. Baseline SHA and burst behavior, representative
selection, savings accounting and complete-link grouping remain intact. Detailed evidence shows
cosine, model/checkpoint identity and whether embedding evidence changed classification.

## Bounded neighbors and grouping

The hybrid extends pHash radius to the selected moderate threshold and merges a bounded local
embedding neighbor set. Eight deterministic random projections sort the vectors; each photo
examines at most 16 neighbors on each side per projection. Actual cosine ranks that bounded
pool, retaining 16 neighbors. Fixed seed: 31704. This is approximate retrieval, not exact ANN.

Complexity is O(P N log N + P N K D), with P=8, K=16 and D=576 or 512. It creates no N×N cosine
matrix, uses no hosted vector database and retains the Phase 2 work limits. It filters to the
textured canonical SHA representatives, preventing exact alternatives from being counted again
in near savings. Existing complete-link checks can reject otherwise valid recovered pairs when
their other group members disagree. Pairwise classifier accuracy and actual grouped accuracy
are therefore reported separately.

## Reproduction

    .venv/bin/photocull hard-duplicate-fixtures --manifest benchmark-output/phase2-v1/manifest.json benchmark-output/phase3-hard-new
    .venv/bin/photocull --cache-dir .photocull evaluate-hybrid --manifest benchmark-output/phase2-v1/manifest.json --hard-manifest benchmark-output/phase3-hard-v1/manifest.json
    .venv/bin/photocull --cache-dir .photocull benchmark-embeddings --evaluation benchmarks/phase3-evaluation.json
    .venv/bin/python benchmarks/phase3_offline_integration.py

Both evaluation and real integration require explicit prior local model setup. Portable pytest
uses mocked encoders and never downloads weights. Hard fixtures refuse a nonempty destination.
See [the completion report](phase3-report.md) for measured results and rejection rationale.
