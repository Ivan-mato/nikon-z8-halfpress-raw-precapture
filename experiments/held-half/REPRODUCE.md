# Reproduce the held-HALF model experiment

These commands are for **Bash on Linux / WSL2, Python 3.12+**, starting at the repository root. All active build/run output must be on a native Linux filesystem, outside the checkout. Use a new workspace each time. Allow about 8 GB of real free disk space and 8 GB RAM; actual use depends on build dependencies and retained logs. An 8 GiB sparse card is a logical size, not a promise that a shared filesystem will preserve holes. On WSL, also check free space on the Windows volume that contains the distro's VHD.

The public scripts were exercised through fresh preparation/build, the documented test-stub repair, both firmware runs, and full content auditing. See the [publication validation receipt](evidence/publication-check/summary.json). This verifies one local environment, not universal host portability or bit-identical builds.

## 1. Supply the external inputs

| Input | Bytes | Required SHA-256 |
|---|---:|---|
| Official Z8 C3.11 package `Z_8_0311.bin` | 99,051,117 | `d67413c2ede6b9ce8887175f20700bd9fbad2a973a4820968c45503d15d80d96` |
| Correctly extracted MAIN, excluding its 2-byte CRC trailer | 81,807,709 | `2b43a31c9de838f84b12416de4348a7004e65be07f853ec56ec2b10f3a8e3853` |
| Official `qemu-11.1.1.tar.xz` | 141,888,716 | `079ffbff8a7111bbc89022107cbabf3bbfd614d5fc9d7cc675991196aca12482` |

The existing [MAIN extraction guide](../../docs/firmware-input.md) explains the independently supplied XOR-table requirement. If you do not already have MAIN, use the existing extractor with your own tables:

```bash
python3 tools/extract_main.py --package /path/to/Z_8_0311.bin \
  --key-json /path/to/private/key.json --output-dir /path/to/new-private-extraction
```

Do not proceed with a different firmware version, guessed table, shifted image or failed hash. No Nikon firmware, XOR tables or installation image is distributed here.

On Ubuntu 24.04, the build uses GCC, make/Ninja, pkg-config, Python/venv, GLib, pixman, zlib and libjpeg development packages, plus `exfatprogs` for a file-backed card:

```bash
sudo apt-get update
sudo apt-get install build-essential ninja-build pkg-config python3-venv \
  libglib2.0-dev libpixman-1-dev zlib1g-dev libjpeg-dev exfatprogs curl

Z8_WORK="$HOME/z8-held-half-reproduction-001"
Z8_PACKAGE=/path/to/Z_8_0311.bin
Z8_MAIN=/path/to/correctly-extracted-MAIN.bin
Z8_QEMU_ARCHIVE=/path/to/qemu-11.1.1.tar.xz
Z8_SCRIPT="$PWD/experiments/held-half/scripts/reproduce.py"
```

Obtain QEMU 11.1.1 from [the official archive](https://download.qemu.org/qemu-11.1.1.tar.xz). The preparer authenticates its full size/hash before extraction. The commands below use an already downloaded archive; no undocumented private source tree is required.

## 2. Prepare and build from empty directories

```bash
python3 "$Z8_SCRIPT" prepare --work "$Z8_WORK" --qemu-archive "$Z8_QEMU_ARCHIVE"
python3 -m venv "$Z8_WORK/venv"
"$Z8_WORK/venv/bin/python" -m pip install -r experiments/held-half/requirements.txt
"$Z8_WORK/venv/bin/python" "$Z8_SCRIPT" build --work "$Z8_WORK" --jobs 2
"$Z8_WORK/venv/bin/python" "$Z8_SCRIPT" test-model --work "$Z8_WORK"
```

Preparation verifies all frozen model files, unpacks 32 synthetic input frames, and extracts QEMU. It deliberately skips one authenticated, unused macOS EDK2 absolute symlink and records that omission. Building applies the frozen 17-file integration/overlay and checks its hashes against the reviewed source, then compiles a new binary. The binary digest is recorded rather than forced to match a previous machine's build.

`test-model` copies the frozen sources, inserts the three-line clock stub documented in [test-clock-stub.patch](test-clock-stub.patch), and runs that copy's suite. It leaves `model/`, the actual QEMU sources and capture driver unchanged. The unmodified delivered suite's compilation failure remains documented; the repaired test result must not be called an original-suite pass.

Never use `python -O` or `PYTHONOPTIMIZE`: inherited model tools and the audit use assertions. The reproduction entry point rejects optimized Python. Do not reuse partial workspaces or relax a hash failure.

## 3. Run both controls and audit the stopped cards

```bash
"$Z8_WORK/venv/bin/python" "$Z8_SCRIPT" run \
  --work "$Z8_WORK" --package "$Z8_PACKAGE" --stock "$Z8_MAIN" \
  --output "$Z8_WORK/run-001"
```

This command locally constructs and independently verifies the seven-instruction candidate, formats a new file-backed exFAT template, and runs candidate held-HALF and stock held-HALF independently with new cards. Each uses the same 32 synthetic inputs and declared experimental model options. The menu sequence selects lossless RAW and the observed continuous release mode. The hold target is 14 virtual seconds, with 85 seconds of settling for the candidate and 12 for stock. Host time varies and is not a frame-rate measurement.

The runner saves controller logs, complete QEMU command lines, firmware/build/source hashes, external-write receipts and actual driver exit codes. It then invokes the independent behavior/card/content auditor. The candidate audit decodes every full CFA array, checks each against its assigned input, checks distinct decoded hashes and RAW strip lengths, decodes three JPEG previews, and runs the wrong-source negative control. The card is read only after owned QEMU shutdown is recorded. Extraction for audit is temporary and does not repair the NEFs or modify the card.

Expected results for this fixed profile:

| Requirement | Candidate | Stock |
|---|---:|---:|
| Driver exit | 0 | 0 |
| Actual HALF/FULL capture gesture | `00 → 10 → 00` | `00 → 10 → 00` |
| Unknown accesses | 0 | 0 |
| Final captures / encodes / NEFs | 27 / 27 / 27 | 0 / 0 / 0 |
| Samples compared to synthetic sources | 1,234,051,200 | 0 (no NEF) |
| Sample differences | 0 | not applicable |
| Distinct decoded RAW arrays | 27 | 0 |
| Wrong-source comparison | rejected, 45,705,600 differences | not applicable |

The stock card may contain `NIKON001.DSC`, a 512-byte card identifier. It is not a photo. Missing output because of driver failure, timeout or unreadable card is not a passing negative control. A different file count is an unexpected result to investigate, not permission to change the acceptance count.

## 4. Inspect or repeat an audit

The main results are `run-001/candidate-audit/report.json` and `run-001/stock-audit/report.json`. Preserve `build-result.json`, `preparation.json`, `model-tests.json`, each `*-exit.json`, `*-transport-audit.json`, and each run's `result.json` / `stderr.log`. Successful report booleans alone are not evidence; the auditor recomputes checks from those inputs and stopped-card data.

```bash
"$Z8_WORK/venv/bin/python" experiments/held-half/scripts/audit_run.py \
  --run "$Z8_WORK/run-001/candidate" --kind candidate \
  --fixtures "$Z8_WORK/fixtures" --output "$Z8_WORK/candidate-audit-second-pass"
```

The new audit output must not already exist. To repeat firmware execution, choose a new `--output`, such as `run-002`. No pre-existing NEF is needed to pass the comparison: expected samples come from the pinned synthetic inputs. The checked-in historical reports are references, not acceptance inputs for new pixel results.

## What this recipe does not validate

This is a two-case model recipe. It does not complete the original regression-three plus sustained-three test matrix, compare per-frame producer snapshots, validate a second decoder, demonstrate true pre-trigger retention, or test a real camera. Virtual timing, synthetic calibration and model contracts remain assumptions. Exact observation times and executable bytes can differ across hosts. Publish failures with source/command/exit identities so their cause can be investigated.

Keep original firmware, full cards and memory dumps private. Public reports should replace local personal paths with placeholders while retaining the original report hashes and stating the redaction. The provided evidence follows that convention.
