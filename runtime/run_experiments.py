# SPDX-License-Identifier: GPL-2.0-or-later
# Uses RdWing's GPL-2.0-or-later Guest, peers and virtual-card tools.
# Route 4 orchestration and publication adaptation, 2026.
"""Run three fresh first-frame model controls; never connect to a camera.

The default validates the complete input plan without starting QEMU. --execute
creates a fresh directory, then runs each case in a separate Python process.
Runtime acceptance requires the complete gesture and stopped-card enumeration;
NEF content/producer auditing calls the separate auditor with actual files;
success is never inferred from file count alone.
"""
import argparse
import errno
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import signal
import struct
import subprocess
import sys
import time

sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
PUBLIC = HERE.parent
PACKAGE_SHA = "d67413c2ede6b9ce8887175f20700bd9fbad2a973a4820968c45503d15d80d96"
STOCK_SHA = "2b43a31c9de838f84b12416de4348a7004e65be07f853ec56ec2b10f3a8e3853"
CANDIDATE_SHA = "2f8207645aeaf8b704613f71d88abc8b27dc5141130219a0176e3ef2ecb1954e"
RAW_SHA = "85878e2e56ee0f6bc10cc0d5dd474375e2ee67bc310d24acf955b0fa5efba293"
HISTORICAL_QEMU_SHA = "e9177cf4dca57872e7d1e4fb27af82a8d1f3ff65be027b22d36075f98af3a618"
MENU = "menu,down,down,down,down,down,down,down,down,down,down,ok,up,ok,menu,menu"
CASES = ("stock-full", "stock-half", "candidate-half")
STRICT_PROPERTIES = {"engine151-loose-admission": "loose_starts",
                     "engine1543-loose-admission": "loose_writes",
                     "unmodeled-tolerant": "tolerated"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path, data):
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def identity(path, size, expected):
    path = Path(path)
    require(path.is_file(), f"input missing: {path}")
    require(path.stat().st_size == size, f"input size mismatch: {path}")
    actual = digest(path)
    require(actual == expected, f"input SHA-256 mismatch: {path}")
    return {"bytes": size, "sha256": actual}


def safe_path(path):
    text = str(path.resolve())
    require(not any(x in text for x in (",", '"', "\n", "\r")),
            "QEMU paths must not contain comma, double quote or a newline")
    return path.resolve()


def verify_build_receipt(receipt, lock, lock_sha, binary_sha, binary_bytes):
    require(receipt.get("schema") == "route4-model-build-v1", "use the public build_model.py receipt schema")
    require(receipt.get("binary_sha256") == binary_sha and receipt.get("binary_bytes") == binary_bytes,
            "QEMU differs from its supplied build receipt")
    require(receipt.get("source_lock_sha256") == lock_sha, "build uses another public model-source lock")
    require(receipt.get("overlay") == lock["qemu"]["prepared_files"], "build source overlay differs from locked files")
    require(receipt.get("qemu_version") == lock["qemu"]["version"], "build QEMU version mismatch")
    require(receipt.get("configure_args") == lock["qemu"]["configure_args"], "build configure arguments mismatch")
    require(receipt.get("target") == lock["qemu"]["ninja_target"], "build target mismatch")


def preflight(args):
    require(sys.version_info >= (3, 11), "runtime needs Python >= 3.11")
    require(not sys.flags.optimize, "do not use -O or PYTHONOPTIMIZE: upstream peers use asserts")
    inputs = {
        "package": identity(args.package, 99051117, PACKAGE_SHA),
        "stock": identity(args.stock, 81807709, STOCK_SHA),
        "candidate": identity(args.candidate, 81807709, CANDIDATE_SHA),
        "raw": identity(args.raw, 90882080, RAW_SHA),
    }
    for name in ("qemu", "build_receipt"):
        require(getattr(args, name).is_file(), f"input missing: {getattr(args, name)}")
    for name in ("package", "stock", "candidate", "raw", "qemu", "output", "model_root"):
        setattr(args, name, safe_path(getattr(args, name)))
    args.build_receipt = args.build_receipt.resolve()
    require(not args.output.exists(), "output already exists; never overwrite a run")
    require(not args.output.is_relative_to(PUBLIC), "keep generated firmware, cards and logs outside the publication tree")
    require(30 <= args.seconds <= 1200 and 5 <= args.settle <= 120, "unsupported duration")
    receipt = json.loads(args.build_receipt.read_text(encoding="utf-8"))
    qemu_sha = digest(args.qemu)
    model_lock_path = HERE / "model-source-lock.json"
    model_lock = json.loads(model_lock_path.read_text(encoding="utf-8"))
    verify_build_receipt(receipt, model_lock, digest(model_lock_path), qemu_sha, args.qemu.stat().st_size)
    preparation = args.model_root.parent / "source-preparation.json"
    require(preparation.is_file() and digest(preparation) == receipt.get("source_preparation_sha256"),
            "source preparation receipt absent or different from build")
    require(receipt.get("builder_sha256") == digest(HERE / "build_model.py"), "build used a different public builder")
    for relative, expected in model_lock["rdwing"]["files_after"].items():
        path = args.model_root / relative
        require(path.is_file() and digest(path) == expected, "prepared upstream/model source changed: " + relative)
    source_lock = json.loads((HERE / "driver-sources.json").read_text(encoding="utf-8"))
    checked = {}
    for relative, expected in source_lock["files"].items():
        require(model_lock["rdwing"]["files_after"].get(relative) == expected, "driver lock disagrees with model-source lock")
        path = args.model_root / relative
        require(path.is_file(), f"model input missing: {relative}")
        require(digest(path) == expected, f"model driver changed: {relative}")
        checked[relative] = expected
    # Run the independent verifier before importing any firmware/controller driver.
    verified = subprocess.run([sys.executable, str(PUBLIC / "tools/verify_candidate.py"),
                              "--package", str(args.package), "--stock", str(args.stock),
                              "--candidate", str(args.candidate)],
                             capture_output=True, text=True)
    require(verified.returncode == 0, "independent candidate verifier failed: " + verified.stderr[-2000:])
    return {"schema": 1, "inputs": inputs, "qemu_sha256": qemu_sha,
            "matches_historical_binary": qemu_sha == HISTORICAL_QEMU_SHA,
            "build_receipt_sha256": digest(args.build_receipt),
            "model_source_lock_sha256": digest(model_lock_path),
            "model_build_mode": "public locked-source build",
            "verified_model_driver_files": checked,
            "candidate_verification": json.loads(verified.stdout),
            "seconds_wall_limit": args.seconds, "settle_virtual_seconds": args.settle,
            "cases": list(CASES), "executed": bool(args.execute),
            "scope": "Functional model only; no factory loader, updater or physical camera execution.",
            "binary_identity_note": "New builds can differ from the historical binary. Source/build receipt consistency is provenance checking, not independent proof of runtime behavior."}


def card_geometry(card):
    require(card.is_file() and card.stat().st_size == 8 * 1024 ** 3, "expected 8 GiB regular card image")
    with card.open("rb") as stream:
        mbr = stream.read(512)
        require(mbr[510:] == b"\x55\xaa" and mbr[450] == 7, "invalid generated MBR")
        start, sectors = struct.unpack_from("<II", mbr, 454)
        require(start == 2048 and (start + sectors) * 512 == card.stat().st_size,
                "unexpected card partition bounds")
        stream.seek(start * 512)
        require(stream.read(11)[3:] == b"EXFAT   ", "card lacks exFAT volume")
    return start, sectors


def sparse_copy(source, target):
    """No dense-copy fallback: an 8 GiB card must retain its zero holes."""
    require(hasattr(os, "SEEK_DATA") and hasattr(os, "SEEK_HOLE"), "sparse file extent support required")
    with source.open("rb") as src, target.open("xb") as dst:
        length = source.stat().st_size
        dst.truncate(length)
        position = 0
        while position < length:
            try:
                start = os.lseek(src.fileno(), position, os.SEEK_DATA)
            except OSError as error:
                if error.errno == errno.ENXIO:
                    break
                raise ValueError("filesystem cannot enumerate sparse extents; use a Linux filesystem") from error
            end = min(length, os.lseek(src.fileno(), start, os.SEEK_HOLE))
            src.seek(start)
            dst.seek(start)
            remaining = end - start
            while remaining:
                block = src.read(min(1024 * 1024, remaining))
                require(bool(block), "short sparse card input")
                dst.write(block)
                remaining -= len(block)
            position = end


def execute_case(args, plan):
    """Called only in a fresh child process, so monkeypatches cannot cross cases."""
    sys.path.insert(0, str(args.model_root / "tools"))
    from full_guest import Guest
    import boot_z8
    from rom_inputs import attach
    from z8_navigation_input import parse_actions, states
    from service_z8_mcu import Peer as BasePeer
    import route4_stream
    watch_environment = {name: name in os.environ for name in ("Z8_WATCH", "Z8_WATCH_OFF")}
    for name in watch_environment:
        os.environ.pop(name, None)
    firmware = args.candidate if args.case == "candidate-half" else args.stock
    half_only = args.case != "stock-full"
    if args.case == "candidate-half":
        os.environ["Z8_ALLOW_PATCHED"] = "1"
    else:
        os.environ.pop("Z8_ALLOW_PATCHED", None)
    g = Guest(firmware, args.qemu, args.raw, args.output)
    g.route4_half_only = half_only
    g.capture_settle = args.settle
    g.capture_menu_file = None
    g.capture_menu_states = states(parse_actions(MENU))
    g.data.update(route4_plan=plan, route4_case=args.case, route4_mcu_inputs=[], route4_gpio_inputs=[])
    g.data["core_watch_environment"] = dict(inherited_present=watch_environment, cleared=True, enabled=False,
                                           ra_is_guest_pc=False)
    g.data["driver_sources"] = {str(path): digest(path) for path in
                                (Path(__file__), HERE / "route4_stream.py")}
    def record_mcu(body, family, source):
        if family == 2:
            require(len(body) > 8, "short MCU input")
            g.data["route4_mcu_inputs"].append(dict(source=source, half=body[7], full=body[8], body_hex=bytes(body).hex()))
            require(not half_only or body[8] == 0, "unexpected FULL in MCU input")
    original_frames = boot_z8.frames
    def boot_frames(body, *pos, **kw):
        family = kw.get("family", pos[0] if pos else None)
        record_mcu(body, family, "boot")
        return original_frames(body, *pos, **kw)
    boot_z8.frames = boot_frames
    original_enqueue = BasePeer.enqueue_external
    def enqueue(peer, body, family):
        record_mcu(body, family, "external queue")
        return original_enqueue(peer, body, family)
    BasePeer.enqueue_external = enqueue
    card = g.out / "capture-card.raw"
    start, sectors = card_geometry(args.card_template)
    sparse_copy(args.card_template, card)
    from inspect_card_volume import catalog
    initial_catalog = catalog(card, base=start * 512)
    require(not any(not row["directory"] for row in initial_catalog["files"]),
            "initial card contains files; do not launch the model")
    save(g.out / "initial-card-catalog.json", initial_catalog)
    g.data["initial_card_catalog"] = initial_catalog
    g.data["initial_card_catalog_sha256"] = digest(g.out / "initial-card-catalog.json")
    machine_index = g.command.index("-M") + 1
    g.command[machine_index] = g.command[machine_index].replace(
        "nikon-z8-lab,", "nikon-z8-full-lab,zr-sd-empty-fixture=on,")
    g.command[machine_index] += ",capture-gpio-model=on,pcie-link-diagnostic-mask=4,pcie-dbi-model=on,pcie-ram-dma-input=on,pcie-image-ram-dma-input=on,pcie-intx-model=on"
    options = json.loads((args.model_root / "tools/capture-model-options.json").read_text(encoding="utf-8"))
    g.command[machine_index] += "," + ",".join(name + "=on" for name in options) + ",z8-timed-single-model=on"
    g.command[machine_index] += "," + ",".join(name + "=off" for name in STRICT_PROPERTIES)
    g.command += ["-device", f"loader,file={firmware},addr=0x40160000,force-raw=on,cpu-num=0",
                  "-drive", f"file={card},if=none,id=card,format=raw", "-device",
                  "nvme,drive=card,serial=WL-Z8-CAPTURE,bus=dw-pcie,addr=0"]
    attach(g)
    for name, address, key in (("preparation", 0x45a403e7, "experimental_preparation_profile"),
                               ("selector5", 0x47f5af45, "experimental_capture_selector5")):
        path = g.out / (name + ".bin")
        path.write_bytes(b"\x01")
        g.command += ["-device", f"loader,file={path},addr={address:#x},force-raw=on"]
        g.data[key] = dict(address=hex(address), value=1, physical_configuration_verified=False)
    g.data["experimental_timed_single"] = dict(enabled=True, physical_timing_verified=False)
    g.data["command"] = g.command
    g.data["virtual_card"] = dict(path=str(card), source=str(args.card_template), partition_start=start, sectors=sectors)
    save(g.out / "plan.json", plan)
    with g:
        def strict_state():
            snapshot = {}
            for name, counter in STRICT_PROPERTIES.items():
                value = g.qmp.command("qom-get", path="/machine", property=name)
                state = g.qmp.command("qom-get", path="/machine", property=name + "-state")
                if isinstance(state, str):
                    state = json.loads(state)
                snapshot[name] = {"property": value, "state": state}
                require(value is False and state.get("enabled") is False and state.get(counter) == 0,
                        "unexpected permissive model property/counter: " + name)
            return snapshot
        g.data["strict_model_before_boot"] = strict_state()
        original_command = g.qmp.command
        def command(name, **kwargs):
            if name == "qom-set" and kwargs.get("property") == "capture-gpio-input":
                value = int(kwargs["value"])
                g.data["route4_gpio_inputs"].append(dict(value=value, half=value & 1, full=(value >> 1) & 1))
                require(0 <= value <= 3, "extra GPIO bits")
                require(not half_only or not value & 2, "unexpected FULL in GPIO input")
            return original_command(name, **kwargs)
        g.qmp.command = command
        try:
            boot_z8.boot(g)
            from gpio_bindings import capture
            bindings = capture(g)
            require(len(bindings) >= 2, "two firmware GPIO bindings required")
            for row, bit, irq in zip(bindings[:2], (4, 5), (59, 60)):
                window = bytes.fromhex(row["irq_hex"])
                require((row["bank"], row["bit"], struct.unpack_from("<III", window, 4),
                         struct.unpack_from("<Q", window, 0x18)[0]) ==
                        (3, bit, (0, bit, irq), 0x40fd9350), "unexpected firmware GPIO binding")
            route4_stream.run(g, args.seconds, None)
            require(len(g.data.get("shutter_inputs", [])) == 5, "incomplete prescribed gesture")
        finally:
            g.qmp.command("stop")
            g.data["strict_model_after_run"] = strict_state()
            g.data["card_model_state"] = {}
            for name in ("engine151-raw-output-state", "engine151-capture-pixels-state", "capture-gpio-state",
                         "raw-pipeline-state", "primary-d980-state", "ccomp-gpio-state"):
                try:
                    g.data["card_model_state"][name] = g.qmp.command("qom-get", path="/machine", property=name)
                except Exception as error:
                    g.data["card_model_state"][name] = dict(error=repr(error))
            state = g.data["card_model_state"]["engine151-raw-output-state"]
            if isinstance(state, str):
                state = json.loads(state)
            if state.get("jobs") == 1 and state.get("acks") == 1 and not state.get("pending"):
                address, size = state["target"], state["bytes"]
                require(0 < size <= 128 * 1024 ** 2 and 0x840000000 <= address < 0x900000000 - size,
                        "producer snapshot outside bounded model RAM")
                dump = g.out / "engine151-raw-side-target.bin"
                g.qmp.hmp(f'pmemsave {address:#x} {size:#x} "{dump}"')
                require(dump.stat().st_size == size, "short producer snapshot")
                g.data["raw_producer_snapshot"] = dict(address=hex(address), bytes=size, file=dump.name,
                                                       sha256=digest(dump))


def delivery_and_settle_evidence(data, run, expected, settle):
    """Recheck received frames/dumps and timing, independently of enqueue counts."""
    before = data.get("route4_before_gesture_delivery", {})
    baseline = before.get("rx_record_count")
    require(type(baseline) is int and baseline >= 0, "missing pre-gesture MCU receipt boundary")
    require(before.get("pending_family2") == 0 and before.get("active_family2") is False,
            "pre-gesture MCU input backlog was not empty")
    received = data.get("continuous_mcu_peer", {}).get("rx", [])
    require(baseline <= len(received), "MCU receipt boundary exceeds records")
    require(all(row.get("index") == i for i, row in enumerate(received)), "MCU receipt indices are not sequential")
    selected = [row for row in received[baseline:] if row.get("family") == 2]
    require(len(selected) == 5, "five actual post-boundary MCU key receipts required")
    sent = data.get("shutter_inputs", [])
    require(len(sent) == 5, "five prescribed gesture records required")
    evidence = []
    captures = data.get("captures", [])
    for row, step, (half, full) in zip(selected, sent, expected):
        body = bytearray(124)
        body[0] = body[4] = 1
        body[7], body[8] = half, full
        require(step.get("body_hex") == body.hex() == row.get("body_hex"), "delivered MCU body differs from the fixed gesture")
        require(row.get("complete") is True, "MCU frame was queued but not fully received")
        packet = bytearray(256)
        packet[0:2] = bytes((2, 1))
        struct.pack_into("<H", packet, 2, len(body))
        packet[8:8 + len(body)] = body
        packet[252:254] = bytes((1, 1))
        packet[255] = (~sum(packet[:255])) & 255
        require(row.get("frame_hex") == packet.hex(), "MCU encoded frame differs from fixed body/checksum")
        label = "continuous-rx-%03d-accepted" % row["index"]
        path = run / (label + ".bin")
        require(path.is_file() and path.read_bytes() == packet, "actual original RX buffer dump differs from expected frame")
        receipts = [entry for entry in captures if entry.get("label") == label]
        require(len(receipts) == 1, "unique accepted RX dump receipt required")
        receipt = receipts[0]
        require(receipt.get("file") == path.name and receipt.get("address") == row.get("rx_pointer") and
                receipt.get("bytes") == 256 and receipt.get("sha256") == digest(path),
                "accepted RX buffer receipt does not bind the actual dump")
        evidence.append({"rx_index": row["index"], "half": half, "full": full, "complete": True,
                         "accepted_buffer_sha256": digest(path)})
    timing = data.get("route4_capture_timing", {})
    require(timing.get("completed") is True and timing.get("termination") == "settle_complete", "complete settle mark missing")
    require(timing.get("required_settle_virtual_seconds") == settle, "recorded settle requirement differs")
    start = timing.get("last_delivery_observed_virtual_seconds")
    finish = timing.get("completion_virtual_seconds")
    release = timing.get("final_release_enqueued_virtual_seconds")
    values = (start, finish, release)
    require(all(type(value) in (int, float) and math.isfinite(value) for value in values), "invalid timing values")
    require(start >= release == sent[-1].get("virtual_seconds"), "settle did not start after final release delivery")
    require(finish - start >= settle, "full virtual settle interval was not observed")
    require(timing.get("delivered_rx_indices") == [row["index"] for row in selected], "settle mark refers to different MCU receipts")
    clock = data.get("route4_final_runtime_clock", {})
    require(type(clock.get("virtual_ns")) is int and
            math.isclose(clock["virtual_ns"] / 1e9, finish, rel_tol=0, abs_tol=1e-9),
            "final model clock does not corroborate settle completion")
    return {"complete_frames": evidence, "last_delivery_observed_virtual_seconds": start,
            "finish_virtual_seconds": finish, "settle_virtual_seconds_observed": finish - start,
            "passed": True}


def producer_snapshot_matches(snapshot, recorded, producer):
    target = producer.get("target")
    size = producer.get("bytes")
    return (type(target) is int and type(size) is int and 0 < size <= 128 * 1024 ** 2 and
            0x840000000 <= target < 0x900000000 - size and
            recorded.get("file") == snapshot.name and recorded.get("address") == hex(target) and
            snapshot.is_file() and snapshot.stat().st_size == recorded.get("bytes") == size and
            digest(snapshot) == recorded.get("sha256"))


def audit_case(args, case, exit_code):
    """Only after the child returns and its owned QEMU is confirmed stopped."""
    from inspect_card_volume import catalog
    from extract_card_file import extract
    run = args.output / case
    row = {"case": case, "child_exit_code": exit_code, "runtime_passed": False, "errors": []}
    result = run / "result.json"
    if not result.is_file():
        row["errors"].append("result.json missing; no card read")
        return row
    data = json.loads(result.read_text(encoding="utf-8"))
    row.update(result_sha256=digest(result), runtime_error=data.get("error"),
               owned_qemu_stopped=data.get("owned_qemu_stopped"))
    require(data.get("owned_qemu_stopped") is True, "QEMU not confirmed stopped; refusing card audit")
    require(data.get("firmware_sha256") == (CANDIDATE_SHA if case == "candidate-half" else STOCK_SHA), "run firmware identity mismatch")
    require(data.get("raw_sha256") == digest(args.raw) == RAW_SHA, "source changed during run")
    require(data.get("qemu_sha256") == digest(args.qemu), "QEMU changed during run")
    strict_ok = True
    for phase in ("strict_model_before_boot", "strict_model_after_run"):
        snapshot = data.get(phase, {})
        for name, counter in STRICT_PROPERTIES.items():
            check = snapshot.get(name, {})
            strict_ok = strict_ok and check.get("property") is False and check.get("state", {}).get("enabled") is False and check.get("state", {}).get(counter) == 0
    row["strict_model_properties_verified"] = strict_ok
    row["watch_environment_cleared"] = data.get("core_watch_environment", {}).get("cleared") is True
    expected = [(0, 0), (1, 0), (1, 1), (1, 0), (0, 0)] if case == "stock-full" else [(0, 0), (1, 0), (1, 0), (1, 0), (0, 0)]
    gesture = [(x["half"], x["full"]) for x in data.get("shutter_inputs", [])]
    gpio = [(int(x["value"]) & 1, (int(x["value"]) >> 1) & 1) for x in data.get("route4_gpio_inputs", [])]
    gpio_metadata_ok = all(0 <= int(x["value"]) <= 3 and
                           (int(x["value"]) & 1, (int(x["value"]) >> 1) & 1) == (x["half"], x["full"])
                           for x in data.get("route4_gpio_inputs", []))
    mcu = data.get("route4_mcu_inputs", [])
    bodies = [bytes.fromhex(x["body_hex"]) for x in mcu]
    input_ok = bool(bodies) and all(len(b) > 8 and (b[7], b[8]) == (r["half"], r["full"]) for b, r in zip(bodies, mcu))
    if case != "stock-full":
        input_ok = input_ok and all(b[8] == 0 for b in bodies)
    initial = bytes.fromhex((data.get("route4_initial_contact_state") or {}).get("bytes", ""))
    initial_ok = len(initial) == 12 and initial[:2] == bytes(2) and initial[4:] == bytes(8)
    busy_masks_zero = data.get("route4_initial_busy_masks") == "0000000000000000"
    row["delivery_and_settle"] = delivery_and_settle_evidence(data, run, expected, args.settle)
    before = data.get("route4_before_gesture_producer", {})
    no_pre_gesture_job = before.get("jobs") == 0 and before.get("acks") == 0 and before.get("pending") is False
    row["before_gesture_producer"] = before
    initial_catalog_path = run / "initial-card-catalog.json"
    initial_catalog = json.loads(initial_catalog_path.read_text(encoding="utf-8"))
    initial_empty = not any(not x["directory"] for x in initial_catalog["files"])
    require(digest(initial_catalog_path) == data["initial_card_catalog_sha256"], "initial catalog changed")
    row["input_audit"] = dict(gesture_matches=gesture == expected, gpio_matches=gpio == expected and gpio_metadata_ok,
                              mcu_metadata_and_full_constraint=input_ok, initial_released=initial_ok,
                              no_pre_gesture_capture_job=no_pre_gesture_job, initial_card_empty=initial_empty,
                              initial_busy_masks_zero=busy_masks_zero,
                              actual_mcu_delivery_and_settle=row["delivery_and_settle"]["passed"])
    card = run / "capture-card.raw"
    start, _ = card_geometry(card)
    # No processes are launched against a group's card after its child exits.
    card_catalog = catalog(card, base=start * 512)
    save(run / "card-catalog.json", card_catalog)
    nefs = [x for x in card_catalog["files"] if not x["directory"] and x["path"].lower().endswith(".nef")]
    row["nef_count"] = len(nefs)
    row["expected_nef_count"] = 0 if case == "stock-half" else 1
    row["extracted_nefs"] = []
    for entry in nefs:
        destination = run / Path(entry["path"]).name
        extracted = extract(card, entry["path"], destination, base=start * 512)
        require(digest(destination) == extracted["sha256"], "extraction digest mismatch")
        row["extracted_nefs"].append({"name": destination.name, "bytes": destination.stat().st_size,
                                      "sha256": extracted["sha256"]})
    producer = data.get("card_model_state", {}).get("engine151-raw-output-state", {})
    if isinstance(producer, str):
        producer = json.loads(producer)
    expected_jobs = row["expected_nef_count"]
    producer_ok = producer.get("jobs") == expected_jobs and producer.get("acks") == expected_jobs and producer.get("pending") is False
    row["final_producer"] = producer
    if expected_jobs:
        snapshot = run / "engine151-raw-side-target.bin"
        recorded = data.get("raw_producer_snapshot", {})
        producer_ok = producer_ok and producer_snapshot_matches(snapshot, recorded, producer)
        if snapshot.is_file():
            row["producer_snapshot"] = {"bytes": snapshot.stat().st_size, "sha256": digest(snapshot)}
            producer_ok = producer_ok and row["producer_snapshot"]["sha256"] == recorded.get("sha256")
    row["producer_state_and_snapshot_match"] = producer_ok
    log = run / "stderr.log"
    with log.open(encoding="utf-8", errors="replace") as stream:
        row["unknown_access_lines"] = sum("Z8_UNKNOWN" in line for line in stream)
    row["content_audit_status"] = "not applicable: expected empty card" if expected_jobs == 0 else "not attempted"
    content_ok = expected_jobs == 0
    if expected_jobs == 1 and len(nefs) == 1 and producer_ok:
        report_path = run / "native-nef-audit.json"
        command = [sys.executable, str(PUBLIC / "tools/audit_nef.py"), "--nef", str(run / Path(nefs[0]["path"]).name),
                   "--source", str(args.raw), "--producer", str(run / "engine151-raw-side-target.bin"),
                   "--require-match", "--report", str(report_path)]
        content = subprocess.run(command, capture_output=True, text=True)
        report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else {}
        row["content_audit_status"] = report.get("status", "report missing")
        row["content_audit_exit_code"] = content.returncode
        if report_path.is_file():
            row["content_audit_sha256"] = digest(report_path)
        content_ok = (content.returncode == 0 and report.get("status") == "PASS_MATCH" and
                      report.get("source", {}).get("sha256") == RAW_SHA and
                      report.get("producer", {}).get("sha256") == row["producer_snapshot"]["sha256"] and
                      report.get("nef", {}).get("sha256") == row["extracted_nefs"][0]["sha256"])
    row["runtime_passed"] = (exit_code == 0 and data.get("error") is None and
                             all(row["input_audit"].values()) and
                             len(nefs) == row["expected_nef_count"] and producer_ok and content_ok and
                             strict_ok and row["watch_environment_cleared"] and row["unknown_access_lines"] == 0)
    return row


def run_owned_child(command, log, timeout):
    """Bound all child work, including boot. Terminate only our new session."""
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True, env=environment)
    def terminate_group():
        for sig, grace in ((signal.SIGTERM, 3), (signal.SIGKILL, 3)):
            try:
                os.killpg(process.pid, sig)
            except ProcessLookupError:
                break
            deadline = time.monotonic() + grace
            while time.monotonic() < deadline:
                process.poll()
                try:
                    os.killpg(process.pid, 0)
                except ProcessLookupError:
                    return True
                time.sleep(0.05)
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            return False
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            return True
        # Do not assert cleanup merely from the Python parent having exited.
        return False
    try:
        code = process.wait(timeout=timeout)
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            return {"exit_code": code, "timed_out": False, "child_pid": process.pid,
                    "orphan_cleanup_required": False, "owned_process_group_gone": True}
        stopped = terminate_group()
        return {"exit_code": code, "timed_out": False, "child_pid": process.pid,
                "orphan_cleanup_required": True, "owned_process_group_gone": stopped}
    except subprocess.TimeoutExpired:
        stopped = terminate_group()
        return {"exit_code": process.returncode, "timed_out": True,
                "child_pid": process.pid, "owned_process_group_gone": stopped}
    except BaseException:
        terminate_group()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("package", "stock", "candidate", "raw", "qemu", "build-receipt", "model-root", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=600)
    parser.add_argument("--settle", type=int, default=25)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--case", choices=CASES, help=argparse.SUPPRESS)
    parser.add_argument("--card-template", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        plan = preflight(args)
        if not args.execute:
            print(json.dumps(plan, indent=2))
            return 0
        require(sys.platform.startswith("linux"), "this runtime recipe supports Linux/WSL Linux only")
        require(os.access(args.qemu, os.X_OK), "QEMU is not executable")
        require(hasattr(os, "SEEK_DATA"), "sparse file support required")
        for library in ("numpy", "rawpy", "PIL"):
            require(importlib.util.find_spec(library) is not None, "missing audit dependency: " + library)
        sys.path.insert(0, str(args.model_root / "tools"))
        if args.case:
            require(args.card_template is not None, "internal child needs its generated card template")
            execute_case(args, plan)
            return 0
        require(shutil.which("mkfs.exfat") and shutil.which("fsck.exfat"), "install Linux exfatprogs first")
        args.output.mkdir(parents=True, exist_ok=False)
        save(args.output / "plan.json", plan)
        from virtual_recording_card import create
        template = args.output / "blank-template.raw"
        template_receipt = create(template, "exfat")
        card_geometry(template)
        save(args.output / "blank-template-receipt.json", template_receipt)
        summary = {"schema": 1, "plan": plan, "cases": [], "all_runtime_controls_passed": False,
                   "native_nef_content_passed": False,
                   "scope": "First-frame model controls plus complete NEF/source/producer checks; no physical-camera claim."}
        for case in CASES:
            command = [sys.executable, str(Path(__file__).resolve())]
            for name in ("package", "stock", "candidate", "raw", "qemu", "build_receipt", "model_root"):
                command += ["--" + name.replace("_", "-"), str(getattr(args, name))]
            command += ["--output", str(args.output / case), "--seconds", str(args.seconds), "--settle", str(args.settle),
                        "--execute", "--case", case, "--card-template", str(template)]
            print("Running " + case, flush=True)
            with (args.output / (case + "-controller.log")).open("x", encoding="utf-8") as log:
                child = run_owned_child(command, log, args.seconds + 180)
            if child["timed_out"] or child.get("orphan_cleanup_required"):
                row = {"case": case, "child": child, "runtime_passed": False,
                       "audit_error": "timeout or remaining child processes; no card read after forced termination"}
            else:
                try:
                    row = audit_case(args, case, child["exit_code"])
                    row["child"] = child
                except Exception as error:
                    row = {"case": case, "child": child, "runtime_passed": False,
                           "audit_error": repr(error)}
            summary["cases"].append(row)
            save(args.output / "runtime-summary.json", summary)
            print(json.dumps(row, ensure_ascii=False), flush=True)
            if not child.get("owned_process_group_gone", False):
                summary["suite_stopped"] = "could not confirm owned timed-out process group disappeared"
                save(args.output / "runtime-summary.json", summary)
                return 1
        summary["all_runtime_controls_passed"] = all(row["runtime_passed"] for row in summary["cases"])
        summary["native_nef_content_passed"] = all(row.get("content_audit_status") == "PASS_MATCH"
                                                   for row in summary["cases"] if row["case"] != "stock-half")
        save(args.output / "runtime-summary.json", summary)
        return 0 if summary["all_runtime_controls_passed"] else 1
    except (ValueError, OSError, KeyError, json.JSONDecodeError) as error:
        print("ERROR: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
