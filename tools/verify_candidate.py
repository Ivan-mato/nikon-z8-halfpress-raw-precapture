#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Independently verify the exact route-4 MAIN candidate using local inputs.

No builder imports, manifest input, third-party decoder, firmware execution, or
camera-safety claim. Python 3.10+, standard library only. Checks remain enabled
under python -O. Full stock authentication anchors the unchanged instructions.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys


def check(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def input_digest(path, expected_size, expected_digest, label):
    check(path.is_file(), f"input missing: {label}: {path}")
    check(path.stat().st_size == expected_size, f"{label} length mismatch")
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    actual = h.hexdigest()
    check(actual == expected_digest, f"{label} SHA-256 mismatch: {actual}")
    return actual


def signed(value, width):
    return value - (1 << width) if value & (1 << (width - 1)) else value


def word(data, address):
    return struct.unpack_from("<I", data, address - 0x40160000)[0]


def branch(pc, encoded):
    if (encoded & 0x7C000000) == 0x14000000:  # B or BL
        displacement = 4 * signed(encoded & 0x03FFFFFF, 26)
    elif ((encoded & 0xFF000010) == 0x54000000 or
          (encoded & 0x7E000000) == 0x34000000):  # B.cond or CBZ/CBNZ
        displacement = 4 * signed((encoded >> 5) & 0x7FFFF, 19)
    else:
        raise ValueError(f"unsupported branch encoding at {pc:#x}")
    return pc + displacement


def movz_w(encoded, expected_register):
    check((encoded & 0xFFE0001F) == (0x52800000 | expected_register),
          "expected unshifted MOVZ W register")
    return (encoded >> 5) & 0xFFFF


def wide_pointer(data, start, register):
    value = 0
    for index in range(4):
        encoded = word(data, start + 4 * index)
        check((encoded & 31) == register, "pointer register mismatch")
        opcode = 0xD2800000 if index == 0 else 0xF2800000
        check((encoded & 0xFF800000) == opcode, "pointer opcode mismatch")
        shift = ((encoded >> 21) & 3) * 16
        immediate = (encoded >> 5) & 0xFFFF
        value = (value & ~(0xFFFF << shift)) | (immediate << shift)
    return value


def verify(stock, candidate):
    check(len(stock) == 81807709 and digest(stock) ==
          "2b43a31c9de838f84b12416de4348a7004e65be07f853ec56ec2b10f3a8e3853",
          "stock MAIN changed after authentication")
    check(len(candidate) == len(stock), "candidate length mismatch")
    differences = [index for index, (a, b) in enumerate(zip(stock, candidate)) if a != b]
    changed_sites = sorted({(index & ~3) + 0x40160000 for index in differences})
    check(changed_sites == [0x40FD93BC, 0x40FD940C, 0x40FD94BC, 0x40FD94C0,
                            0x40FD94C4, 0x40FDC858, 0x40FDF6C0],
          "changed instruction sites differ from the seven allowed sites")
    check(len(differences) == 21, f"changed byte count is {len(differences)}, expected 21")
    decoded = []
    for pc, target in ((0x40FD93BC, 0x40FD9420), (0x40FD940C, 0x40FD95C0),
                       (0x40FD94C4, 0x40FD9420)):
        encoded = word(candidate, pc)
        check((encoded & 0xFC000000) == 0x14000000, "patched branch must be B, not BL")
        actual = pc + 4 * signed(encoded & 0x03FFFFFF, 26)
        check(actual == target, f"wrong patched branch target at {pc:#x}")
        decoded.append({"pc": hex(pc), "instruction": "B", "target": hex(actual),
                        "signed_imm26": signed(encoded & 0x03FFFFFF, 26),
                        "link_register_written": False})
    check(movz_w(word(candidate, 0x40FD94BC), 9) == 1, "W9 must receive one")
    decoded.append({"pc": "0x40fd94bc", "instruction": "MOVZ W9,#1,LSL#0"})
    encoded = word(candidate, 0x40FD94C0)
    check((encoded & 0xFFE00C00) == 0x38000000,
          "bridge must use integer byte unscaled store without writeback")
    rt, rn = encoded & 31, (encoded >> 5) & 31
    offset = signed((encoded >> 12) & 0x1FF, 9)
    check((rt, rn, offset) == (9, 8, -4), "wrong STURB operand")
    x8 = wide_pointer(candidate, 0x40FD938C, 8)
    check(x8 == 0xA03BD055C and x8 + offset == 0xA03BD0558, "wrong release-byte pointer")
    decoded.append({"pc": "0x40fd94c0", "instruction": "STURB W9,[X8,#-4]",
                    "imm9_unsigned": (encoded >> 12) & 0x1FF,
                    "signed_displacement": offset, "bytes_written": 1,
                    "writeback": False, "live_x8": hex(x8),
                    "effective_address": hex(x8 + offset)})
    for pc in (0x40FDC858, 0x40FDF6C0):
        check(movz_w(word(stock, pc), 0) == 0x24, "unexpected stock polling selector")
        check(movz_w(word(candidate, pc), 0) == 0x23, "unexpected patched polling selector")
        decoded.append({"pc": hex(pc), "instruction": "MOVZ W0,#0x23,LSL#0",
                        "original_logical": "0x24"})

    # Independent context checks: decode original control-flow targets and
    # callback pointers. The exact full-file diff already proves these unchanged.
    edges = {0x40FD9374: 0x40FD93F0, 0x40FD93A0: 0x40FD94BC,
             0x40FD93B8: 0x40FD57EC, 0x40FD9408: 0x40FD946C,
             0x40FD9434: 0x40FD9538, 0x40FD944C: 0x40FD95A8,
             0x40FD9468: 0x40FD57EC, 0x40FD954C: 0x40FD57EC,
             0x40FD9568: 0x40FD95C0, 0x40FD9588: 0x40FD57EC,
             0x40FDC85C: 0x40FDC9A8, 0x40FDF6C4: 0x40FDC9A8}
    for pc, target in edges.items():
        check(branch(pc, word(candidate, pc)) == target, f"original edge mismatch at {pc:#x}")
    callbacks = {str(slot): wide_pointer(candidate, start, 1) for slot, start in
                 ((0, 0x40FD93A4), (1, 0x40FD9450), (2, 0x40FD9538), (3, 0x40FD956C))}
    check(callbacks == {"0": 0x40FDFC44, "1": 0x40FDC9C8,
                        "2": 0x40FDC8EC, "3": 0x40FDCA40}, "original callback mismatch")
    windows = []
    for begin, end in ((0x40FD9350, 0x40FD9600), (0x40FDC80C, 0x40FDC8EC),
                       (0x40FDF6BC, 0x40FDF6E8), (0x40FD54C8, 0x40FD55CC),
                       (0x40FD57EC, 0x40FD5844)):
        a, b = begin - 0x40160000, end - 0x40160000
        windows.append({"begin": hex(begin), "end_exclusive": hex(end), "bytes": b - a,
                        "stock_sha256": digest(stock[a:b]),
                        "candidate_sha256": digest(candidate[a:b])})
    candidate_sha = digest(candidate)
    check(candidate_sha == "2f8207645aeaf8b704613f71d88abc8b27dc5141130219a0176e3ef2ecb1954e",
          f"complete candidate SHA-256 mismatch: {candidate_sha}")
    return {"schema": "route4-independent-static-verification-v1",
            "decision": "PASS: exact candidate reconstruction and static instruction checks only",
            "stock_sha256": digest(stock), "candidate_sha256": candidate_sha,
            "payload_bytes": len(candidate), "changed_bytes": len(differences),
            "changed_instruction_count": len(changed_sites),
            "changed_sites": [hex(pc) for pc in changed_sites],
            "independent_decodes": decoded,
            "unchanged_branch_targets": {hex(k): hex(v) for k, v in edges.items()},
            "original_callback_slots": {k: hex(v) for k, v in callbacks.items()},
            "windows": windows, "execution_performed": False,
            "physical_camera_verified": False,
            "limitations": ["Not an installation artifact; module/container checksums are not rebuilt.",
                            "Static checks do not prove receiver acceptance, image writing, or camera safety.",
                            "No universal indirect-consumer or all-camera-mode coverage is claimed."],
            "verifier_sha256": digest(Path(__file__).read_bytes())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--stock", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    args = parser.parse_args()
    try:
        package_sha = input_digest(args.package, 99051117,
                                  "d67413c2ede6b9ce8887175f20700bd9fbad2a973a4820968c45503d15d80d96",
                                  "package")
        input_digest(args.stock, 81807709,
                     "2b43a31c9de838f84b12416de4348a7004e65be07f853ec56ec2b10f3a8e3853", "stock MAIN")
        check(args.candidate.is_file(), f"input missing: candidate: {args.candidate}")
        check(args.candidate.stat().st_size == 81807709, "candidate length mismatch")
        result = verify(args.stock.read_bytes(), args.candidate.read_bytes())
        result["package_sha256"] = package_sha
        result["package_extraction_performed"] = False
        print(json.dumps(result, indent=2))
    except (OSError, ValueError, struct.error) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
