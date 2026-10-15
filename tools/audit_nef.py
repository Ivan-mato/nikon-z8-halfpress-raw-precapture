# SPDX-License-Identifier: GPL-3.0-only
"""Read-only NEF content audit for the bounded Z8 C3.11 lossless14 model profile.

Fresh parsing code; no firmware, private paths, prior helper or manifest import.
Profile and CFA/packed14 comparison rules derive from RdWing/z8-qemu's
tools/nef_ifds.py and tools/audit_nef.py (GPL-2.0-or-later).
PASS_MATCH means both supplied sample sources match, not same-run provenance.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import struct
import sys

WIDTH, HEIGHT, SOURCE_WIDTH, SOURCE_HEIGHT, STRIDE = 8280, 5520, 8256, 5504, 14496
MAX_NEF_BYTES = 256 * 1024 * 1024
TYPE_SIZE = {1:1, 2:1, 3:2, 4:4, 5:8, 6:1, 7:1, 8:2, 9:4, 10:8, 11:4, 12:8, 13:4}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(blob):
    return hashlib.sha256(blob).hexdigest()


def identify(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1048576), b""):
            digest.update(block)
    return dict(name=path.name, bytes=path.stat().st_size, sha256=digest.hexdigest())


def read_ifd(data, address, base=0, bounds=None):
    lo, hi = bounds or (0, len(data))
    require(lo <= address <= hi - 2, "IFD address exceeds bounded region")
    count = struct.unpack_from("<H", data, address)[0]
    require(count <= 1024 and address + 2 + 12 * count + 4 <= hi, "Invalid IFD extent/count")
    tags = {}
    for index in range(count):
        cursor = address + 2 + 12 * index
        tag, kind, items, pointer = struct.unpack_from("<HHII", data, cursor)
        require(kind in TYPE_SIZE and items <= MAX_NEF_BYTES, "Invalid TIFF type/count")
        length = items * TYPE_SIZE[kind]
        offset = cursor + 8 if length <= 4 else base + pointer
        require(lo <= offset <= hi and length <= hi - offset, "TIFF value exceeds bounded region")
        require(tag not in tags, "Duplicate TIFF tag")
        blob = data[offset:offset + length]
        tags[tag] = dict(kind=kind, count=items, offset=offset, bytes=length, blob=blob)
    return tags, struct.unpack_from("<I", data, address + 2 + 12 * count)[0]


def integers(tags, key):
    require(key in tags, "Missing TIFF tag " + hex(key))
    entry = tags[key]
    require(entry["kind"] in (3, 4) and 0 < entry["count"] <= 1024, "Invalid integer tag " + hex(key))
    code = "H" if entry["kind"] == 3 else "I"
    return list(struct.unpack("<" + code * entry["count"], entry["blob"]))


def singleton(tags, key):
    values = integers(tags, key)
    require(len(values) == 1, "Expected one TIFF value for " + hex(key))
    return values[0]


def bounded_region(data, offset, length, label):
    require(length > 0 and 0 <= offset <= len(data) and length <= len(data) - offset,
            label + " exceeds file")
    return data[offset:offset + length]


def inspect_structure(data):
    from PIL import Image
    require(len(data) >= 8 and data[:4] == b"II*\0", "Expected little-endian TIFF/NEF header")
    first = struct.unpack_from("<I", data, 4)[0]
    queue, seen, rows = [first], set(), []
    while queue:
        address = queue.pop(0)
        if not address:
            continue
        require(address not in seen and len(seen) < 32, "Repeated/cyclic or excessive image IFDs")
        seen.add(address)
        tags, next_ifd = read_ifd(data, address)
        rows.append((address, tags))
        if 330 in tags:
            queue.extend(integers(tags, 330))
        queue.append(next_ifd)
    require(bool(rows), "No image IFD")
    root = rows[0][1]
    require(272 in root and root[272]["kind"] == 2 and
            root[272]["blob"].rstrip(b"\0") == b"NIKON Z 8", "Expected NIKON Z 8 model metadata")
    raw_rows = [(a,t) for a,t in rows if 254 in t and 262 in t and
                singleton(t,254) == 0 and singleton(t,262) == 32803]
    require(len(raw_rows) == 1, "Expected exactly one Bayer RAW image")
    raw_address, raw = raw_rows[0]
    expected = {256:WIDTH, 257:HEIGHT, 258:14, 259:34713}
    require(all(singleton(raw,k) == v for k,v in expected.items()), "Unexpected RAW dimensions/bit depth/compression")
    strip_offset, strip_size = singleton(raw,273), singleton(raw,279)
    strip = bounded_region(data,strip_offset,strip_size,"RAW strip")
    packed_sizes = [((WIDTH * 7 * channels // 4 + 15) // 16 * 16) * HEIGHT for channels in (1,3)]
    require(strip_size > 4 and strip_size not in packed_sizes, "LibRaw packed-size fallback is not lossless coding evidence")
    exif, _ = read_ifd(data, singleton(root,0x8769))
    require(0x927C in exif, "Missing Nikon MakerNote")
    maker = exif[0x927C]
    require(maker["kind"] == 7 and maker["blob"][:10] == b"Nikon\0\x02\x11\0\0", "Unexpected Nikon MakerNote profile")
    base = maker["offset"] + 10
    limit = maker["offset"] + maker["bytes"]
    require(base + 8 <= limit and data[base:base+4] == b"II*\0", "Invalid Nikon nested TIFF header")
    nested = base + struct.unpack_from("<I",data,base+4)[0]
    note, _ = read_ifd(data,nested,base,(maker["offset"],limit))
    require(0x96 in note and note[0x96]["kind"] == 7, "Missing Nikon linearization metadata")
    linear = note[0x96]["blob"]
    require(linear.startswith(b"F0" + struct.pack("<4H",2048,2048,2048,2048)), "Expected F0 lossless14 predictor metadata")
    previews = []
    for _, tags in rows:
        if 513 not in tags and 514 not in tags:
            continue
        off, size = singleton(tags,513), singleton(tags,514)
        blob = bounded_region(data,off,size,"JPEG preview")
        require(blob.startswith(b"\xff\xd8") and blob.endswith(b"\xff\xd9"), "JPEG markers missing or incomplete")
        with Image.open(io.BytesIO(blob)) as preview:
            require(preview.format == "JPEG", "Preview is not JPEG")
            preview.load()
            dimensions = list(preview.size)
        previews.append(dict(offset=off,bytes=size,dimensions=dimensions,sha256=sha(blob)))
    require(sorted(x["dimensions"] for x in previews) == [[160,120],[1620,1080],[8256,5504]],
            "Expected exactly three native JPEG preview sizes")
    return dict(raw_ifd_address=raw_address, width=WIDTH,height=HEIGHT,bits=14,
                compression=34713, model="NIKON Z 8",packed_size_fallback_excluded=True,
                linearization=dict(bytes=len(linear),sha256=sha(linear),profile="F0/four predictors 2048"),
                raw_strip=dict(offset=strip_offset,bytes=strip_size,sha256=sha(strip)),previews=previews)


def compare_samples(nef, source_path, producer_path, result):
    import numpy as np
    import rawpy
    from PIL import __version__ as pillow_version
    result["dependencies"] = dict(numpy=np.__version__,rawpy=rawpy.__version__,libraw=list(rawpy.libraw_version),Pillow=pillow_version)
    source, packed = None, None
    if source_path:
        result["source"] = dict(**identify(source_path),compared=False)
        require(source_path.stat().st_size == 32 + SOURCE_WIDTH * SOURCE_HEIGHT * 2, "Invalid NZ9RAW1 source length")
        with source_path.open("rb") as stream:
            header = stream.read(32)
        require(struct.unpack("<8s6I",header) == (b"NZ9RAW1\0",SOURCE_WIDTH,SOURCE_HEIGHT,14,0,0,16383),
                "Source must be 8256x5504 RGGB,14bit,black0,white16383 NZ9RAW1")
        source = np.memmap(source_path,dtype="<u2",mode="r",offset=32,shape=(SOURCE_HEIGHT,SOURCE_WIDTH))
        require(not np.any(source > 16383), "Source contains samples exceeding 14bit white")
    if producer_path:
        result["producer"] = dict(**identify(producer_path),compared=False,same_run_provenance_verified=False)
        require(producer_path.stat().st_size == STRIDE * HEIGHT, "Producer must be complete 5520 rows at 14496-byte stride")
        packed = np.memmap(producer_path,dtype=np.uint8,mode="r",shape=(HEIGHT,STRIDE))
    x = np.arange(WIDTH,dtype=np.int64)
    source_x = (x // 2 * (SOURCE_WIDTH // 2) // (WIDTH // 2)) * 2 + (x & 1)
    mismatch_source, mismatch_producer, compared = 0, 0, 0
    with rawpy.imread(str(nef)) as decoded:
        pixels = decoded.raw_image
        require(pixels.shape == (HEIGHT,WIDTH) and pixels.dtype == np.uint16, "Unexpected full LibRaw RAW array")
        require(int(pixels.max()) <= 16383, "Decoded samples exceed 14bit")
        for y in range(HEIGHT):
            if source is not None:
                sy = (y // 2 * (SOURCE_HEIGHT // 2) // (HEIGHT // 2)) * 2 + (y & 1)
                mismatch_source += int(np.count_nonzero(pixels[y] != source[sy,source_x]))
            if packed is not None:
                groups = packed[y,:WIDTH * 14 // 8].reshape(-1,7).astype(np.uint64)
                words = np.zeros(len(groups),dtype=np.uint64)
                for byte in range(7):
                    words |= groups[:,byte] << (8 * byte)
                unpacked = np.stack([(words >> (14 * lane)) & 16383 for lane in range(4)],axis=1).reshape(-1)
                mismatch_producer += int(np.count_nonzero(pixels[y] != unpacked))
            compared += WIDTH
        full = pixels.astype("<u2",copy=False).tobytes()
        require(len(full) == 91411200 and compared == 45705600, "Incomplete decode/comparison")
        result["decoded"] = dict(width=WIDTH,height=HEIGHT,samples=compared,bytes=len(full),
            minimum=int(pixels.min()),maximum=int(pixels.max()),sha256_u16le=sha(full),
            sha512_u16le=hashlib.sha512(full).hexdigest())
    if source is not None:
        result["source"].update(compared=True,samples_compared=compared,mismatches=mismatch_source)
    if packed is not None:
        result["producer"].update(compared=True,samples_compared=compared,mismatches=mismatch_producer)
    require(mismatch_source == 0, "Decoded RAW differs from supplied CFA-resampled source")
    require(mismatch_producer == 0, "Decoded RAW differs from supplied packed14 producer")
    if source is not None and packed is not None:
        return "PASS_MATCH"
    if source is not None:
        return "PARTIAL_SOURCE_MATCH"
    if packed is not None:
        return "PARTIAL_PRODUCER_MATCH"
    return "PASS_DECODE_ONLY"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nef",type=Path,required=True)
    parser.add_argument("--source",type=Path,help="Actual supplied NZ9RAW1 source; no automatic synthesis")
    parser.add_argument("--producer",type=Path,help="Actual packed14 snapshot; audit does not infer same-run provenance")
    parser.add_argument("--require-match",action="store_true",help="Exit 2 unless BOTH sources are supplied and every sample matches")
    parser.add_argument("--report",type=Path,required=True,help="Fresh JSON report, never overwrite evidence")
    args = parser.parse_args()
    result = dict(status="FAIL",tool_sha256=identify(Path(__file__))["sha256"],source=dict(compared=False),
                  producer=dict(compared=False,same_run_provenance_verified=False),
                  camera_verified=False,pretrigger_history_verified=False,independent_second_decoder=False,
                  exiftool_validation_performed=False,
                  scope="Bounded file content and optional supplied samples; not runtime causality, same-run provenance or device acceptance")
    # Reserve output before work. Never overwrite an input, even on failure.
    try:
        report = args.report.open("x",encoding="utf-8")
    except OSError as error:
        print("Cannot create fresh report: " + str(error),file=sys.stderr)
        return 2
    try:
        require(0 < args.nef.stat().st_size <= MAX_NEF_BYTES,"NEF size exceeds audit profile")
        data = args.nef.read_bytes()
        result["nef"] = dict(name=args.nef.name,bytes=len(data),sha256=sha(data))
        result["structure"] = inspect_structure(data)
        status = compare_samples(args.nef,args.source,args.producer,result)
        result["status"] = status
        if args.require_match and status != "PASS_MATCH":
            result["required_match_missing"] = True
            exit_code = 2
        else:
            exit_code = 0
    except Exception as error:
        result["error"] = str(error)
        result["status"] = "FAIL"
        exit_code = 2
    with report:
        json.dump(result,report,ensure_ascii=False,indent=2)
        report.write("\n")
    print(json.dumps(dict(status=result["status"],report=args.report.name,
                         error=result.get("error"),required_match_missing=result.get("required_match_missing",False)),indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
