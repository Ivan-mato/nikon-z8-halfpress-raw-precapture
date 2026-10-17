# Evidence index and interpretation

The checked-in JSON files are **path-redacted derivatives** of retained local audit reports. Each wrapper records the SHA-256 of the original unredacted report. Redacted bytes have a different digest. These summaries are not raw cards or complete execution logs, and their hashes alone do not prove the claims. [The runnable recipe](../REPRODUCE.md) lets reviewers generate fresh evidence from their own firmware inputs.

| Report | Supports | Does not establish |
|---|---|---|
| `independent-content.json` | 27 original NEFs identical to original card entries, full structure/preview/source checks | physical sensor input or per-frame producer comparison |
| `replay-halfheld-002-content.json` | new card's 27 NEFs, complete source match, decoded sequence agrees with original | bit-identical executables or actual 10 fps |
| `replay-stock-half-002-content.json` | stock run contains no NEF | arbitrary stock settings or other scenarios |
| `*-independent-behavior.json` | actual MCU receiver bytes, GPIO sequence, counters, release/tail observations | instantaneous release cancellation |
| `independent-transport-summary.json` | permitted external writes and zero recorded guard violations in accepted replays | authenticity of synthetic ROM/calibration |
| `wrong-source-negative-control.json` | full-array comparison rejects the wrong frame's source | completeness of all other fault detection |
| `independent-build.json`, `complete-build-source-comparison.json` | clean rebuild and full prepared source identity comparison | bit-for-bit binary reproducibility |
| `binary-section-comparison.json` | executable sections do differ | a proven cause for those differences |
| `manifest-check.json`, `original-source-bindings.json` | delivery identities and source-frame order | runtime correctness by themselves |
| `model-tests-result.json` | original test suite compilation failure | a passing original suite |
| `model-tests-with-harness-fix-result.json` | isolated clock-stub repair makes the suite pass | a model semantics change |
| `VERDICT.json` | concise bounded conclusion and missing gates | completion of the original six-case matrix |
| [publication-check/summary.json](publication-check/summary.json) and accompanying reports | actual fresh build, both runs and audits through the public CLI, plus sample-only audit | external replication or the remaining six-case/producer gates |

The audit scripts were independently written relative to the supplied acceptance functions, but run by the same local project with AI assistance. “Independent” in historical filenames describes that implementation/checking separation. It does **not** mean unaffiliated third-party replication. Reports name the actual rawpy/LibRaw versions; all RAW decoding ultimately uses LibRaw.

The original source and delivery are retained locally without rewriting failed checks. Publication portability changes are separately tested; publication-check evidence, when present, records those new runs rather than relabeling an older execution as a run of new scripts.
