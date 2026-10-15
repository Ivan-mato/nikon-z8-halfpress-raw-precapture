#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Extract only the authenticated stock Z8 C3.11 MAIN using user-supplied tables.

Python 3.10+, standard library only. No key recovery, firmware download,
package modification, signature-key derivation, target execution or device I/O.
The format is documented by WonderLantern/nikon-fw-key-tool, fixed reference
33426e892afd329a3b366b73776bcf53b9ac4ee8. No external tool code is imported.
"""
import argparse
import binascii
import hashlib
import json
from pathlib import Path
import struct
import sys

PACKAGE_BYTES = 99051117
PACKAGE_SHA256 = "d67413c2ede6b9ce8887175f20700bd9fbad2a973a4820968c45503d15d80d96"
DECODED_SHA256 = "7dec1be784812c32ea3b735f18b46e260b15b0a960f5a3dc40c4197d0b07fc0a"
MAIN_BYTES = 81807709
MAIN_SHA256 = "2b43a31c9de838f84b12416de4348a7004e65be07f853ec56ec2b10f3a8e3853"
NAMES = ("ex2070_030000.bi", "_tpj01_0210.bin", "eg2070_0311b0.bi",
         "vr2070_010100.bi", "li2070_0311b0.bi")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, "Duplicate JSON key")
        value[key] = item
    return value


def read_tables(path):
    require(path.is_file(), "Key JSON input missing")
    require(0 < path.stat().st_size <= 1024 * 1024, "Key JSON exceeds bounded input size")
    encoded = path.read_bytes()
    document = json.loads(encoded.decode("utf-8-sig"), object_pairs_hook=unique_object)
    require(isinstance(document, dict), "Key JSON must be an object")
    result = []
    for name in ("T1", "T2", "T3"):
        value = document.get(name)
        require(isinstance(value, str), name + " must be a hexadecimal string")
        try:
            table = bytes.fromhex(value)
        except ValueError:
            raise ValueError(name + " is not valid hexadecimal") from None
        require(len(table) == 256, name + " must contain exactly 256 bytes")
        result.append(table)
    # No key bytes or full JSON content are copied into the receipt.
    return result, sha256(encoded)


def decode(raw, tables):
    require(raw[32:64] == b" " * 32, "Missing plaintext body label")
    t1, t2, t3 = tables
    # Two low index bytes repeat every 64 KiB. Adding T3 gives the complete
    # 16 MiB period, allowing C-backed integer XOR instead of 99M Python steps.
    translations = [bytes(value ^ mask for value in range(256)) for mask in range(256)]
    low = b"".join(t1.translate(translations[value]) for value in t2)
    stream = b"".join(low.translate(translations[value]) for value in t3)
    period = 1 << 24
    require(len(stream) == period, "Unexpected XOR period")
    decoded = bytearray(raw)
    for file_start in range(64, len(raw), 65536):
        size = min(65536, len(raw) - file_start)
        # The XOR index is BODY relative, including its 32-byte space label.
        index = (file_start - 32) % period
        end = index + size
        mask = stream[index:end] if end <= period else stream[index:] + stream[:end-period]
        value = int.from_bytes(raw[file_start:file_start+size], "little") ^ int.from_bytes(mask,"little")
        decoded[file_start:file_start+size] = value.to_bytes(size, "little")
    return decoded


def inspect_modules(plain):
    body = memoryview(plain)[32:]
    require(body[:32] == b" " * 32, "Invalid decoded body label")
    count, directory_size, r0, r1 = struct.unpack_from(">4I", body, 32)
    require(count == 5 and directory_size == 48 + 32 * count, "Unexpected module directory")
    require(r0 == r1 == 0, "Nonzero directory reserved fields")
    require(bytes(body[-14:]) == bytes(14), "Nonzero package trailer padding")
    cursor, end, rows, main = directory_size, len(body)-16, [], None
    require(directory_size <= end, "Directory exceeds body")
    for index in range(count):
        record = 48 + 32 * index
        name_raw, offset, size, r0, r1 = struct.unpack_from(">16s4I", body, record)
        expected_name = NAMES[index]
        require(name_raw == expected_name.encode("ascii").ljust(16,b"\0"), "Unexpected module name/order")
        require(r0 == r1 == 0, "Nonzero module reserved fields")
        require(offset == cursor and size >= 2 and size <= end-offset,
                "Module directory gap, overlap or out-of-range extent")
        module = body[offset:offset+size]
        recorded_crc = int.from_bytes(module[-2:], "big")
        computed_crc = binascii.crc_hqx(module[:-2], 0)
        residue = binascii.crc_hqx(module, 0)
        require(computed_crc == recorded_crc and residue == 0,
                "Module CRC mismatch: " + expected_name)
        rows.append(dict(name=expected_name,body_offset=offset,file_offset=offset+32,
                         bytes=size,sha256=sha256(module),crc16=f"{recorded_crc:04x}",crc16_residue=residue))
        if index == 2:
            main = bytes(module[:-2])
        cursor += size
    require(cursor == end, "Module extents do not meet package trailer")
    package_crc = int.from_bytes(body[-16:-14], "big")
    require(binascii.crc_hqx(body[:-16],0) == package_crc and
            binascii.crc_hqx(body[:-14],0) == 0, "Package CRC mismatch")
    require(main is not None and len(main) == MAIN_BYTES and sha256(main) == MAIN_SHA256,
            "Extracted MAIN identity mismatch")
    return main, rows, dict(stored=f"{package_crc:04x}",residue=0,
                           body_coverage_excluding_crc=[0,len(body)-16],
                           body_coverage_including_crc=[0,len(body)-14])


def extract(args):
    require(not args.output_dir.exists(), "Output directory already exists")
    require(args.package.is_file(), "Input missing: exact Z_8_0311.bin is required")
    require(args.package.stat().st_size == PACKAGE_BYTES, "Original package length mismatch")
    raw = args.package.read_bytes()
    require(len(raw) == PACKAGE_BYTES and sha256(raw) == PACKAGE_SHA256, "Original package SHA-256 mismatch")
    tables, key_json_sha256 = read_tables(args.key_json)
    plain = decode(raw,tables)
    require(len(plain) == PACKAGE_BYTES and sha256(plain) == DECODED_SHA256,
            "Decoded package SHA-256 mismatch; supplied XOR tables do not decode this exact input")
    require(binascii.crc_hqx(b"123456789",0) == 0x31c3, "CRC implementation check failed")
    main, modules, package_crc = inspect_modules(plain)
    receipt = dict(status="PASS_EXACT_STOCK_EXTRACTION",tool_sha256=sha256(Path(__file__).read_bytes()),
        original=dict(bytes=len(raw),sha256=sha256(raw)),
        decoded=dict(bytes=len(plain),sha256=sha256(plain)),key_json_sha256=key_json_sha256,
        modules=modules,package_crc=package_crc,
        crc_formula="CRC16 polynomial0x1021 init0 refin=false refout=false xorout0; direct update, stored big-endian",
        main=dict(file="stock-MAIN.bin",bytes=len(main),sha256=sha256(main),module_crc_removed_bytes=2),
        signature_key_recovered=False,header_keyed_digest_recomputed=False,
        scope="Exact existing original package identity plus decoded structure/CRCs; no edited package or device acceptance",
        external_format_reference=dict(repository="https://github.com/WonderLantern/nikon-fw-key-tool",
            commit="33426e892afd329a3b366b73776bcf53b9ac4ee8"))
    # All input and structure checks finish before any directory/output write.
    # exist_ok=False plus xb/x also rejects an intervening creator.
    args.output_dir.mkdir(parents=False,exist_ok=False)
    with (args.output_dir/"stock-MAIN.bin").open("xb") as target:
        target.write(main)
    with (args.output_dir/"extraction-receipt.json").open("x",encoding="utf-8") as target:
        json.dump(receipt,target,indent=2)
        target.write("\n")
    return receipt


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package",type=Path,required=True)
    parser.add_argument("--key-json",type=Path,required=True)
    parser.add_argument("--output-dir",type=Path,required=True,
                        help="Fresh child directory of an existing private directory")
    args=parser.parse_args()
    try:
        receipt=extract(args)
        print(json.dumps(dict(status=receipt["status"],main=receipt["main"]),indent=2))
        return 0
    except Exception as error:
        print(json.dumps(dict(status="FAIL",error=str(error)),indent=2),file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
