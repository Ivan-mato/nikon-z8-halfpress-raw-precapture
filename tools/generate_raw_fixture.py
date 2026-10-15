# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
# Adapted from RdWing/z8-qemu tools/make_cmos.py: fixed capture profile,
# exclusive output, streaming identity check and a machine-readable receipt.
"""Generate the historical synthetic capture input; no firmware or camera access."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

WIDTH, HEIGHT, BITS = 8256, 5504, 14
EXPECTED_BYTES = 90882080
EXPECTED_SHA256 = "85878e2e56ee0f6bc10cc0d5dd474375e2ee67bc310d24acf955b0fa5efba293"


def generate(output):
    import numpy as np
    white = (1 << BITS) - 1
    bars = np.array([[1,1,1], [1,1,0], [0,1,1], [0,1,0],
                     [1,0,1], [1,0,0], [0,0,1], [0,0,0]], dtype=np.float64)
    row = bars[np.arange(WIDTH) * 8 // WIDTH]
    digest, written = hashlib.sha256(), 0
    # Exact original transfer/rounding expressions retained intentionally.
    with output.open("xb") as target:
        header = struct.pack("<8s6I", b"NZ9RAW1\0", WIDTH, HEIGHT, BITS, 0, 0, white)
        target.write(header); digest.update(header); written += len(header)
        for y in range(HEIGHT):
            rgb = row * (.25 + .75 * y / (HEIGHT - 1))
            linear = np.where(rgb <= .04045, rgb / 12.92, ((rgb + .055) / 1.055) ** 2.4)
            pixels = np.empty(WIDTH, dtype="<u2")
            pixels[0::2] = np.rint(linear[0::2, 0 if y % 2 == 0 else 1] * white)
            pixels[1::2] = np.rint(linear[1::2, 1 if y % 2 == 0 else 2] * white)
            blob = pixels.tobytes()
            target.write(blob); digest.update(blob); written += len(blob)
    actual = digest.hexdigest()
    if written != EXPECTED_BYTES or actual != EXPECTED_SHA256:
        raise ValueError("Generated fixture differs from historical identity; do not run the model with it")
    return dict(status="PASS_EXACT_FIXTURE", name=output.name, bytes=written,
                sha256=actual, numpy=np.__version__, width=WIDTH, height=HEIGHT,
                bits=BITS, cfa="RGGB", black=0, white=white,
                source="RdWing/z8-qemu tools/make_cmos.py capture profile",
                scope="Synthetic test input, not camera data or a firmware artifact")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True,
                        help="Fresh file in an existing directory outside the repository")
    args = parser.parse_args()
    try:
        result = generate(args.output)
        print(json.dumps(result, indent=2))
        return 0
    except Exception as error:
        print(json.dumps(dict(status="FAIL", error=str(error)), indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
