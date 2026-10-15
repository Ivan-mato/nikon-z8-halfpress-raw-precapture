#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Build the exact route-4 research MAIN payload; never an update package.

Python 3.10+, standard library only. All firmware inputs must be supplied locally.
This program does not execute firmware or establish camera compatibility/safety.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

BASE = 0x40160000
PACKAGE_SIZE = 99051117
PACKAGE_SHA256 = "d67413c2ede6b9ce8887175f20700bd9fbad2a973a4820968c45503d15d80d96"
MAIN_SIZE = 81807709
MAIN_SHA256 = "2b43a31c9de838f84b12416de4348a7004e65be07f853ec56ec2b10f3a8e3853"
CANDIDATE_SHA256 = "2f8207645aeaf8b704613f71d88abc8b27dc5141130219a0176e3ef2ecb1954e"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def authenticate(path, expected_size, expected_sha256, label):
    require(path.is_file(), f"input missing: {label}: {path}")
    size = path.stat().st_size
    require(size == expected_size, f"{label} length mismatch: {size} != {expected_size}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    actual = digest.hexdigest()
    require(actual == expected_sha256, f"{label} SHA-256 mismatch: {actual}")
    return actual


def b_instruction(source, target):
    displacement = target - source
    require(displacement % 4 == 0, "unaligned branch")
    require(-(1 << 27) <= displacement < (1 << 27), "branch out of range")
    return 0x14000000 | ((displacement // 4) & 0x03FFFFFF)


def build(stock):
    # Authenticate the bytes used below, in addition to the input-file check.
    require(len(stock) == MAIN_SIZE and sha256(stock) == MAIN_SHA256,
            "stock bytes do not match the required MAIN")
    edits = [
        (0x40FD93BC, b_instruction(0x40FD93BC, 0x40FD9420), "B 0x40FD9420"),
        (0x40FD940C, b_instruction(0x40FD940C, 0x40FD95C0), "B 0x40FD95C0"),
        (0x40FD94BC, 0x52800000 | (1 << 5) | 9, "MOVZ W9,#1,LSL#0"),
        (0x40FD94C0, 0x38000000 | ((-4 & 0x1FF) << 12) | (8 << 5) | 9,
         "STURB W9,[X8,#-4]"),
        (0x40FD94C4, b_instruction(0x40FD94C4, 0x40FD9420), "B 0x40FD9420"),
        (0x40FDC858, 0x52800000 | (0x23 << 5), "MOVZ W0,#0x23,LSL#0"),
        (0x40FDF6C0, 0x52800000 | (0x23 << 5), "MOVZ W0,#0x23,LSL#0"),
    ]
    candidate = bytearray(stock)
    rows = []
    for address, encoded, assembly in edits:
        offset = address - BASE
        replacement = struct.pack("<I", encoded)
        original = stock[offset:offset + 4]
        require(len(original) == 4, f"site outside MAIN: {address:#x}")
        candidate[offset:offset + 4] = replacement
        rows.append({"va": hex(address), "file_offset": hex(offset),
                     "original_word_sha256": sha256(original),
                     "replacement_hex": replacement.hex(), "assembly": assembly})
    changed = [index for index, (a, b) in enumerate(zip(stock, candidate)) if a != b]
    allowed = {address - BASE + byte for address, _, _ in edits for byte in range(4)}
    require(len(candidate) == MAIN_SIZE, "payload length changed")
    require(len(changed) == 21 and set(changed).issubset(allowed),
            "unexpected full-file byte differences")
    require(sha256(candidate) == CANDIDATE_SHA256, "candidate SHA-256 mismatch")
    return candidate, rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True, type=Path,
                        help="locally supplied original Z_8_0311.bin (identity check only)")
    parser.add_argument("--stock", required=True, type=Path,
                        help="locally supplied exact, already-extracted stock MAIN")
    parser.add_argument("--output-dir", required=True, type=Path,
                        help="new directory; existing directories are never overwritten")
    args = parser.parse_args()
    try:
        require(not args.output_dir.exists(), "output directory already exists")
        package_sha = authenticate(args.package, PACKAGE_SIZE, PACKAGE_SHA256, "package")
        authenticate(args.stock, MAIN_SIZE, MAIN_SHA256, "stock MAIN")
        candidate, rows = build(args.stock.read_bytes())
        report = {
            "schema": "route4-research-build-v1",
            "scope": "exact static model-payload reconstruction; NOT an installable firmware package",
            "package_sha256": package_sha, "stock_sha256": MAIN_SHA256,
            "candidate_sha256": sha256(candidate), "payload_bytes": len(candidate),
            "modified_instruction_count": 7, "changed_bytes": 21,
            "package_extraction_performed": False, "execution_performed": False,
            "physical_camera_verified": False, "edits": rows,
            "builder_sha256": sha256(Path(__file__).read_bytes()),
        }
        args.output_dir.mkdir(parents=True, exist_ok=False)
        with (args.output_dir / "route4-half-native-nef.model-payload").open("xb") as out:
            out.write(candidate)
        with (args.output_dir / "build-receipt.json").open("x", encoding="utf-8", newline="\n") as out:
            json.dump(report, out, indent=2)
            out.write("\n")
        print(json.dumps(report, indent=2))
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
