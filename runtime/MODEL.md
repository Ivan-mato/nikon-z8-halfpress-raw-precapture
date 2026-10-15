# Fixed model source and clean build

This recipe reconstructs the source used by the historical local experiment.
It prepares and compiles an emulator; it does not execute Nikon firmware, make
an update package, or establish camera operation. A successful build requires
the separate input/NEF acceptance runs before it supports a runtime result.

## Fixed sources

| Component | Fixed identity |
| --- | --- |
| RdWing Z8 source | Commit `c24e33460ab311b8b120b19ba25f532ccef1b391`, Git tree `846ed3de2cd851d9be7d3cd0e77359288a8640a6` |
| RdWing source ZIP | 304,389 B; SHA-256 `55b2e03490a1117c84d1476a6e4a1c879aeac0dba1bdddd16ccaa7b4fb8c5d74` |
| QEMU | Official `qemu-11.1.1.tar.xz`, 141,888,716 B; SHA-256 `079ffbff8a7111bbc89022107cbabf3bbfd614d5fc9d7cc675991196aca12482` |
| Historical model binary | SHA-256 `e9177cf4dca57872e7d1e4fb27af82a8d1f3ff65be027b22d36075f98af3a618` |

The exact download URLs, pre/post patch hashes, 54 upstream file identities,
and 16 prepared QEMU file identities are in [model-source-lock.json](model-source-lock.json).
The upstream archive was fetched from its fixed GitHub commit, compared with
the local snapshot, and patched in a new directory. Both patches applied
without relaxed context, and the 16 resulting source hashes matched the
historical source. The binary hash is a reference, not a promise that a different
compiler, build path or dependency set emits identical executable bytes.

## What differs from upstream

[model-overlay.patch](model-overlay.patch) modifies three files relative to
the fixed RdWing commit:

- `qemu/nikon-z8-lab.c`: experimental multi-frame input/state, optional relaxed
  admission/tolerant diagnostics, an engine153 offset-4 admission change, and
  the corrected ownership/freeing of multi-frame pixel sources.
- `qemu/nikon-z8-d980.h`: source rotation, cache invalidation and observations.
- `tools/full_guest.py`: an explicit local patched-payload switch and recording
  of the actual payload hash. The switch alone is insufficient authentication;
  the experiment driver must still enforce its exact firmware allowlist.

The optional `engine151-loose-admission`, `engine1543-loose-admission` and
`unmodeled-tolerant` machine properties are not enabled by the accepted first
frame experiment. Their absence does **not** make this a pristine upstream
model: the engine153 admission change and other source modifications remain.

The fixed upstream `qemu/prepare_source.py` adds the Nikon overlay and changes
QEMU's Kconfig, Meson registration, aarch64 default configuration, DesignWare
DMA limit handling, and TCG breakpoint removal across vCPUs. These inherited
integration changes retain upstream attribution.

### Correction: two additional QEMU core changes

The earlier build receipt listed 14 integration/overlay files. It did not
cover the locally modified `system/physmem.c` and `accel/tcg/cputlb.c` copied
into the historical source tree. Thus matching those 14 entries, or the nine
Nikon C/H files alone, was not a complete source lock.

[model-qemu-core.patch](model-qemu-core.patch) now retains both exact changes:

- `physmem.c` inserts a conditional write observer at `flatview_write`.
- `cputlb.c` inserts observers in the scalar `do_st_1/2/4/8` helpers, passing
  virtual and computed physical addresses to the observation function.

They read `Z8_WATCH` and `Z8_WATCH_OFF` and may print write observations. The
added observer bodies do not request guest-memory writes or redirect guest PC.
They still add host calls, address calculations and possible logging; even
with the variables unset this is not a proof of zero execution/timing effect
or all-path semantic equivalence. The runtime launcher must remove both
variables from the child environment and record that condition.

An inherited comment incorrectly describes `ra` as an AArch64 guest PC. It is
a TCG helper host return-address value and must not be used as guest-PC
evidence without a separately verified translation. These hooks also do not
observe every possible store path. Positive observations can support only
their verified interpretation; zero hits do not prove a write never happened.
The exact comments are retained in the patch for source identity, with these
corrections explicitly recorded here.

The provenance review compared all 78,691 regular files in the official QEMU
archive with the historical source: seven archive files differed, comprising
the five inherited integration files and these two core files. The nine Nikon
C/H files are additional overlay files. This is a source comparison, not a
fresh execution or an independent proof of the model's hardware accuracy.

### Archive-link preparation correction

The first complete preparation attempt failed with `absolute archive symlink`.
The earlier patch-application check used only the affected source files and
did not exercise full archive extraction; it must not be described as a passed
complete preparation run. Its failed output directory is retained.

The authenticated QEMU archive contains 72 symbolic links. Exactly one points
outside the source tree: `roms/edk2/EmulatorPkg/Unix/Host/X11IncludeHack` points
to `/opt/X11/include`. This is an EDK2 XCODE/macOS host include bridge, not an
input to the Linux `qemu-system-aarch64` build. The preparer checks its exact
member name, link type and target, records it, and **does not create it**.
It does not follow or relax containment checks for this link. This deliberate
omission means the prepared tree is not an extraction intended to build every
bundled ROM project on every host.

All 72 link identities are now listed in the source lock. The 71 internal links
are checked as a complete graph for escapes, cycles and indirect traversal
through the omitted link before they are created. Unexpected names or targets
fail. Tests reject direct/indirect escapes, cycles, changed targets and an
unreviewed omission; those tests do not substitute for a fresh complete
preparation and build run.

## Prepare and compile

Use Linux, Python 3.10+, Git, a C/C++ compiler, Ninja, pkg-config, and the QEMU
build dependencies. The tested environment uses Ubuntu 24.04; needed packages
include `build-essential`, `ninja-build`, `pkg-config`, `python3-venv`,
`libglib2.0-dev`, `libpixman-1-dev`, `zlib1g-dev`, and `libjpeg-dev`. QEMU's
configure step reports missing dependencies; it may acquire its own Python
build dependencies. No dependency-install command is run by these scripts.

From the repository root, select a new workspace **outside the repository**:

```sh
python3 runtime/prepare_model.py --workspace /path/to/route4-model --cache /path/to/source-cache
python3 runtime/build_model.py --workspace /path/to/route4-model --jobs 2
```

If archives already exist, add `--rdwing-archive /path/to/rdwing.zip` and/or
`--qemu-archive /path/to/qemu-11.1.1.tar.xz` to the preparation command. Cached
files receive the same full length/hash check as downloads. Missing explicit
archive paths or wrong identities fail rather than falling back to another
version. Fresh source and build directories are required; earlier experiments
or compiled objects are never reused or overwritten.

Preparation checks archive paths, keeps extraction inside the new directory,
applies both patches with `git apply --check`, verifies all locked resulting
files, and writes `source-preparation.json`. Compilation uses the historical
configure arguments:

```text
--target-list=aarch64-softmmu --disable-docs --disable-werror
```

It builds the `qemu-system-aarch64` Ninja target, preserves `build.log`, and
writes `build/z8-build-receipt.json` with toolchain, actual binary hash, source
lock identity and a false runtime-acceptance flag. It never starts QEMU.
Allow roughly 1 GiB for extracted sources and 1–3 GiB for build artifacts;
reserve at least 4 GiB plus later experiment storage. On WSL, also check the
host volume's actual free space rather than only the virtual disk maximum.

See [NOTICE.md](NOTICE.md) for attribution and the separate runtime licensing.
