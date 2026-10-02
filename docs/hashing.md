# Hashing methodology

Phase 1 calculates three 64-bit values, encoded as 16-character lowercase hexadecimal strings.
Inputs are orientation-correct RGB then converted to grayscale by Pillow. Resizing uses Lanczos.
Hash component version: `hashes_v1`. Algorithms are fixed in this version and recorded in its
parameters alongside Pillow, NumPy and OpenCV versions.

- aHash: resize to 8×8, compare each pixel strictly greater than the mean.
- dHash: resize to 9×8, compare each right neighbor strictly greater than its left neighbor.
- pHash: resize to 32×32, OpenCV DCT, use top-left 8×8 low-frequency coefficients, compare strictly
  greater than their median excluding DC. Force the DC output bit to 0. The resulting effective
  comparison information is 63 bits in a 64-bit storage representation.

Bits are row-major, first bit most significant. Hamming distance uses XOR popcount. There is no
similarity threshold, duplicate classification, clustering or recommendation in this phase.
Byte-identical file copies have equal content SHA-256 and perceptual hashes. Different file paths
still have different fast fingerprints. Re-encoding/resizing may perturb hashes. Crops, rotations,
flat colors and repetitive patterns are known limitations; hashes can collide on different images.
Uniform images often share zero hashes and must not later be classified as duplicates from this
signal alone. The generated checkerboard tolerance tests do not imply universal invariance.
