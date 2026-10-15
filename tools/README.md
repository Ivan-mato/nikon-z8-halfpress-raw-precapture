# Reconstruct the research payload

Requires Python 3.10 or later; no packages to install. Supply both files yourself:

| Input | Bytes | SHA-256 |
| --- | ---: | --- |
| Original `Z_8_0311.bin` | 99,051,117 | `d67413c2ede6b9ce8887175f20700bd9fbad2a973a4820968c45503d15d80d96` |
| Already-extracted stock MAIN | 81,807,709 | `2b43a31c9de838f84b12416de4348a7004e65be07f853ec56ec2b10f3a8e3853` |

These tools authenticate the package and MAIN separately. They do not extract or
decrypt a firmware package, download inputs, or infer a MAIN from another version.
A matching filename is insufficient. Missing or nonmatching inputs cause failure.

If you have the package and your own legacy XOR tables, the separate
[`extract_main.py`](extract_main.py) provides a checked extraction path; see
[firmware-input.md](../docs/firmware-input.md). No keys are bundled, and this
project does not claim that the single Z8 package suffices to recover all tables.

Run from the repository root, substituting your local input locations. Choose an
output directory **outside this repository** that does not already exist:

```sh
python tools/build_candidate.py --package /path/to/Z_8_0311.bin --stock /path/to/stock-MAIN.bin --output-dir ../route4-private-build
python tools/verify_candidate.py --package /path/to/Z_8_0311.bin --stock /path/to/stock-MAIN.bin --candidate ../route4-private-build/route4-half-native-nef.model-payload
```

On Windows, use quoted Windows paths. Both commands also work with `python -O`;
validation does not depend on Python assertions. An existing build directory is
rejected rather than overwritten.

The output must be 81,807,709 bytes with SHA-256:

```text
2f8207645aeaf8b704613f71d88abc8b27dc5141130219a0176e3ef2ecb1954e
```

It changes seven AArch64 instruction words (21 differing bytes). The independent
verifier checks the complete byte diff, hand-decodes branches and the byte store,
checks original callback/branch context, and hashes the whole result. It imports
no builder code and accepts no build manifest as evidence. Its JSON output reports
window hashes rather than distributing original firmware byte windows.

**This is not an installable firmware package.** There are no rebuilt module or
container checksums, version changes, loader changes, or installation instructions.
Successful reconstruction proves the exact static experiment can be reproduced;
it does not rerun QEMU or prove camera operation, RAW image output, or recovery.
Do not upload inputs or generated payloads to GitHub.

## Re-run the static regression tests

The regression entry exercises the actual command-line tools, including
`python -O`, isolated Python, wrong inputs, edits outside the seven sites,
wrong branch targets, wrong store addressing, and refusal to overwrite output:

```sh
python tools/test_static_tools.py --package /path/to/Z_8_0311.bin --stock /path/to/stock-MAIN.bin --output-dir ../route4-static-tests
```

The new private output directory retains all 13 case results and logs plus a
candidate and deliberately invalid payload. These are local test assets, not
publication files. A deliberate rejection is an expected test outcome.

## Beyond static bytes

- [NEF content and exact synthetic source](../docs/nef-validation.md): additional
  Python dependencies, complete decoding, and optional source/producer comparison.
- [Fixed model source and build](../runtime/MODEL.md): public upstream archives
  plus the exact local source patches.
- [Three runtime controls](../runtime/RUN.md): separate fresh cards, actual input
  delivery, stopped-card inspection and full content checks.

Static validation, file decoding, model execution and physical-camera operation
are separate claims. Follow the scope and actual test results for each.
