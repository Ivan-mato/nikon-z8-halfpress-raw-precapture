# Runtime source attribution and license scope

The model and controller source originates from RdWing's Z8 adaptation of
WonderLantern's Z9 emulator. RdWing's original notice is preserved in
[model-upstream-NOTICE.md](model-upstream-NOTICE.md), including its WonderLantern
baseline and LibRaw/Dave Coffin format-reference attribution.

The supplied model diffs retain inherited source copyright and licensing.
The local experimental additions include multi-frame input, observation hooks,
model admission changes, patched-payload handling and an ownership correction;
they are not claimed as upstream QEMU/RdWing behavior or hardware specifications.
`route4_stream.py` is a modified RdWing controller and retains its original
copyright/SPDX notice. Modifications and exact source identities are described
in [MODEL.md](MODEL.md) and `model-source-lock.json`.

The runtime Python sources and the local additions in the model patches use
**GPL-2.0-or-later**, except where an individual file states otherwise. The
GPL version 2 text is preserved in [COPYING.GPL-2.0](COPYING.GPL-2.0).
The repository root's GPL-3.0-only notice for its separately written static
tools and research text does not replace the upstream notices in these runtime
derivatives.

QEMU retains its own per-file licenses. In particular, the original
`system/physmem.c` and `accel/tcg/cputlb.c` identify Fabrice Bellard and use
**LGPL-2.1-or-later**. Their original notices remain in the prepared source.
The GPL-2.0-or-later SPDX line in `model-qemu-core.patch` describes the local
additions; it is not a statement that inherited QEMU code was originally GPL
or that its per-file notices have been replaced. The original LGPL text is
included as [COPYING.LIB](COPYING.LIB). No single license label here replaces
the licenses of all source files in the combined QEMU tree.

The following documents are unmodified copies from authenticated sources:

- [COPYING](COPYING) and [LICENSES/QEMU-LICENSE.txt](LICENSES/QEMU-LICENSE.txt)
  come from RdWing commit
  [`c24e33460ab311b8b120b19ba25f532ccef1b391`](https://github.com/RdWing/z8-qemu/tree/c24e33460ab311b8b120b19ba25f532ccef1b391).
  The latter explains QEMU's distribution-level and per-file license scope;
  it is not another copy of the GPL text. These paths also preserve the
  original relative links in `model-upstream-NOTICE.md`, which is unchanged.
- [COPYING.LIB](COPYING.LIB) comes from the official QEMU 11.1.1 source archive
  authenticated by `model-source-lock.json`; it contains the LGPL version 2.1.
- `COPYING.GPL-2.0` and `COPYING` are identical copies of the GPL version 2 text
  supplied by that fixed RdWing source.

This directory distributes source recipes, patches and research descriptions,
not Nikon firmware, keys, camera parameter dumps, virtual cards or compiled
emulators. Referenced or locally generated material retains its own rights;
the source license does not relicense user-provided firmware or entire derived
firmware payloads. No camera updater or installation/recovery claim is included.
