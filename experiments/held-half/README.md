# Held half-press → native NEF: a bounded model experiment

**Model-only result, using Nikon Z8 C3.11 MAIN and a locally modified QEMU functional model. No physical camera has been tested. This is not a 10 fps result or an installable firmware release.**

In the recorded experiment, one half-press held for about 14 virtual seconds, followed by release, resulted in 27 distinct NEF files written by the firmware to an initially empty virtual card. All 27 files decoded completely with LibRaw, and every decoded CFA sample matched its assigned synthetic input. The stock MAIN produced no NEF under the same held-half profile. A separate local clean build and replay obtained the same counts and decoded sequence.

The files are written during half-press and queue drain. Retaining pre-trigger frames and saving them after a full press has **not** been demonstrated here. The repository name describes the broader research direction, not an achieved pre-capture feature.

**[Reproduce the experiment](REPRODUCE.md)** · [Audit the published samples without firmware](samples/README.md) · [Chinese overview](../../README.md) · [Model and source provenance](MODEL.md) · [Evidence guide](evidence/README.md)

## What was observed

Both runs below used the same frozen model sources and seven-instruction candidate. “Local verification replay” means a new source extraction/build and separately written audit in the same local research environment, with AI assistance. It is **not** a reproduction by an external person, lab, or organization; no such reproduction is claimed.

| Check | Supplied run, re-audited locally | Local verification replay |
|---|---:|---:|
| Held HALF duration, virtual seconds | 14.041163562 | 14.059186841 |
| Capture gesture `(HALF,FULL)` | `00 → 10 → 00` | `00 → 10 → 00` |
| Captured / encoded just before release | 26 / 5 | 26 / 5 |
| Final captures / encodes / NEFs | 27 / 27 / 27 | 27 / 27 / 27 |
| NEFs with complete source comparison, zero mismatches | 27 / 27 | 27 / 27 |
| Stock MAIN, held HALF, final NEFs | 0 | 0 |
| `Z8_UNKNOWN` log lines; driver exit | 0; 0 | 0; 0 |
| Last capture first observed after release, virtual seconds | 0.073179453 | 0.081274679 |
| Last encoding after release, virtual seconds | 63.299703620 | 63.256705547 |
| Observed unchanged capture/encode counts after reaching 27, virtual seconds | 21.840784 | 21.867317 |

One additional capture submission occurred after the release GPIO input in both runs. The record does not prove that it had already been queued inside the firmware. “Stops after release” therefore means that capture became quiescent after a short observed delay; it does not mean immediate cancellation. The encoder then needed about 63.3 virtual seconds to finish its queue. Event times are model timestamps, not physical-camera performance measurements.

The portable publication CLI was subsequently exercised from a new source/build directory. It also produced 27 candidate NEFs and zero stock NEFs, with every sample matching and both drivers exiting 0. Its new binary, exact timings and reports are recorded separately in [publication-check/summary.json](evidence/publication-check/summary.json). The sample-only public CLI also passed. These are further local checks, not additional external replications.

## What the NEF checks establish

Each file contains an 8280 × 5520, 14-bit Nikon F0 lossless RAW array. The auditor compares all **45,705,600** decoded samples per file: **1,234,051,200** comparisons per 27-file group. Every comparison was exact; all 27 decoded pixel hashes were distinct. RAW strip lengths matched individual encoder completions, and three embedded JPEG previews per file decoded. No file was repaired or accepted by transitive similarity to another NEF.

The inputs are 32 deterministic **640 × 480 synthetic Bayer frames**, expanded with the model's CFA-phase-preserving mapping. The output dimensions do not establish 45.7 million independent sensor measurements or a physically accurate ISP. The wrong-source negative control compares NEF 1 with the input for frame 2 and rejects it with 45,705,600 differing samples.

The audit has separately written exFAT/TIFF parsing and source comparison, but RAW decoding uses **one implementation**, LibRaw through rawpy. No second RAW decoder or camera-generated input was verified. The 27-frame runs do **not** contain a packed producer snapshot for every frame. Their result is a complete **source-to-decoded-NEF match**, not the earlier project's source-plus-producer `PASS_MATCH` qualification.

## Scope of the implementation

The candidate MAIN has the same length and SHA-256 as the earlier seven-instruction candidate: `2f8207645aeaf8b704613f71d88abc8b27dc5141130219a0176e3ef2ecb1954e`. It changes 21 bytes in seven instruction windows; no new code cave is used. The model supplies synthetic sensor/ROM/configuration inputs and implements the selected multi-frame device contracts. The firmware issues capture and file-writing operations; the functional model performs the emulated pixel transport and lossless encoding.

The replay driver supplies a single HALF contact edge and a later release. The audit checks the MCU receiver bytes and GPIO history. A host-transport guard rejects CPU-register writes, arbitrary RAM writes and undeclared input properties; the accepted replay recorded no violation. Synthetic ROM/configuration data are still loaded explicitly at startup. This guard does not make those data authentic camera calibration, and it is not a security sandbox or a proof of hardware equivalence.

This experiment has its own frozen model under `model/`. It does **not** replace `runtime/` or imply that the earlier first-frame model passed continuous capture. The original three regression cases plus three sustained cases have not all been rerun against this model. Changing a model assumption requires a new source identity and new evidence, not reuse of the results above.

## Known limits and retained failures

- Physical-camera behavior, installation, recovery, actual frame rate and 10 fps remain untested. The recorded LCD setting was 5; functional-model timing is not a calibrated throughput test.
- Fast release, repeated press/release, a full press during capture, long holds, buffer exhaustion and other shooting modes remain untested.
- The original delivered model tests fail to compile `test_raw_owners.py` because a diagnostic clock stub is missing. The documented test command applies only that stub in a separate test copy. The full suite then passed; the model and capture driver used for the replay remain byte-for-byte unchanged.
- Binary hashes differ between the supplied build and local clean build. The source comparison and actual replay support the result; bit-for-bit reproducible binaries are not claimed.
- A shorter initial run failed its predeclared timing/quiescence checks. Earlier Windows-mounted active-log runs failed with host I/O errors. They are not counted as successful or as stock negative controls.
- Zero unknown accesses means these runs stayed within implemented model semantics. It does not prove that those semantics match Nikon silicon.

## Reproduction and attribution

The public package includes the exact 80-file model snapshot, its hashes, the exact synthetic fixtures, the original 27 synthetic NEFs in a compressed sample archive, portable Linux commands, separately written audit code and path-redacted numerical reports. Firmware, XOR tables, private RAM dumps and virtual cards are not included. Users must supply the exact original package and correctly extracted MAIN for execution; owning the package alone does not resolve the external MAIN-extraction prerequisites. Sample-only auditing requires no Nikon firmware and cannot by itself establish execution provenance.

The QEMU base, Z8/Z9 models, native firmware execution, ordinary NEF path, hardware models and codec foundations come from upstream projects. Their authorship is retained in the sources and [MODEL.md](MODEL.md). This publication contributes the integration record, bounded reproduction recipe and checks, and makes no first/only-implementation claim. Source provenance is provided independently of any claim that upstream maintainers endorse this experiment.

Please report failures as well as successes. Include the publication commit, input hashes, build receipt, driver exits and both audit reports with personal paths redacted. A timeout, incomplete input delivery, unknown access, decode failure or nonzero sample difference is a failing or invalid run. Do not silently change the expected count to turn a mismatch into a pass.
