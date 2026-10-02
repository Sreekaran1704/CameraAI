# Photographic demo samples (public_demo_v2)

The public demo bundles 12 AI-generated photographic samples in `assets/demo/`. No personal photos, remote image requests, or runtime image generation are involved. Generated source renders are retained in `assets/demo/sources/`; `benchmarks/generate_public_demo.py` packages reproducible JPEGs with authored teaching timestamps. The asset license is CC0-1.0.

| Samples | What visitors can observe |
| --- | --- |
| 01–04: mountain lake | Original, byte-identical copy, recompressed copy, and resized copy. Exact copies should look identical; file encoding and resolution differences can be visually subtle. |
| 05–09: café | Sharp latte art and croissant texture, obvious missed focus, dark shadows, washed-out highlights, and a smaller rendition. |
| 10–12: running dog | Three visibly different leg positions from the same scene, with synthetic capture times two seconds apart. |

Overview opens with a side-by-side comparison. Visitors select a category and a variant, see what to inspect, then see actual measured quality warnings and detected relations. Fixture descriptions are kept separate from predictions and never used as analysis features. Uploaded images are not assigned these teaching labels.

The unchanged detector finds one exact group, one near group, one burst group, and three events. The café variants trigger low sharpness, underexposure, and overexposure respectively. The sharp café has no quality warning. Its resized variant does not pass the near-duplicate threshold; we do not force a match. Measured details and resource sizes are in `benchmarks/demo-v2-validation.json`. These teaching fixtures establish no human preference accuracy or held-out precision/recall claim.

Historical Phase 7 performance measurements used the former `public_demo_v1` illustrations. Their recorded timings are retained and explicitly labeled; they do not describe performance on these larger photographic samples.

## Generation prompt set and provenance

Mode: built-in image generation, three new renders and five reference-image edits, opaque backgrounds. The following records the prompt intent used for each output. All scenes exclude people, text, branding, and watermarks.

1. `lake.jpg`: realistic sharp morning mountain lake; red canoe beside a wooden dock, evergreens, textured rocks, and reflections.
2. `cafe.jpg`: realistic crisp blue ceramic cappuccino with detailed latte art, flaky croissant on a white plate, textured wooden table, window light, plant and background bokeh.
3. `cafe-blurred.jpg`: edit the café reference; heavily missed focus across the entire frame, recognizable objects but lost fine edges; preserve composition.
4. `cafe-dark.jpg`: edit the café reference; severe approximately four-stop underexposure, lost shadow detail, preserve composition.
5. `cafe-bright.jpg`: edit the café reference; approximately three-stop overexposure with clipped white highlights across foam, table, and croissant; preserve composition.
6. `dog-1.jpg`: realistic sharp golden retriever running left to right beside a lake on grass, orange ball, full body, front paws extended mid-stride.
7. `dog-2.jpg`: edit the first dog frame into the next moment; same background, lighting, subject scale and camera, forepaws landing, hind legs back, head lower.
8. `dog-3.jpg`: edit the first dog frame into another moment; same background and camera, forelegs bent toward chest, hind legs gathered, airborne, ears back.

The exposure and focus examples are generated visual edits, not calibrated camera measurements. The dog sequence is synthetic, not an actual captured burst. Python only encodes JPEGs, creates identical/recompressed/resized copies, and authors metadata; it does not create the blur, exposure, or pose edits. Original source renders are 1536 × 1024; resized teaching copies are 768 × 512.

To reproduce the packaged dataset from retained sources, run `.venv/bin/python benchmarks/generate_public_demo.py`. This requires no network or image-generation service.
