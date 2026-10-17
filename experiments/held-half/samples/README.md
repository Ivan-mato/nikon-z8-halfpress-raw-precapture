# Original synthetic NEF samples

[Download the 27-NEF archive](z8-held-half-model-27-nefs.zip): 6,688,579 bytes compressed, 948,097,331 bytes of NEFs after extraction. These highly compressible images are synthetic patterns, not camera photographs. The archive contains the original supplied NEFs without repair, a file/hash manifest and a scope note. Its SHA-256 is `ef0e257fb157f4524e33b83aa97593976c29de11d3e48e4446f09a6591ad0293`; see [asset-manifest.json](asset-manifest.json).

You can audit their entire RAW contents without owning Nikon firmware. Use Python 3.12+ on Linux or a compatible host with the listed rawpy wheels, from the repository root:

```bash
python3 -m venv /path/to/new-sample-audit-venv
/path/to/new-sample-audit-venv/bin/python -m pip install -r experiments/held-half/requirements.txt
/path/to/new-sample-audit-venv/bin/python experiments/held-half/scripts/audit_samples.py \
  --output /path/to/new-private-sample-audit
```

Use an output directory outside the repository that does not already exist. The auditor extracts one NEF at a time, decodes all 45,705,600 CFA samples, compares them directly with the corresponding pinned synthetic source, checks TIFF/MakerNote/preview structure, verifies distinct decoded hashes, and rejects a deliberately wrong source. It writes `report.json` and removes its temporary extracted samples. To inspect the original files in another decoder, extract the archive yourself.

This verifies the published files' content. It does **not** prove how the files were produced, check the original virtual card, demonstrate a physical camera, or replace [a full new execution](../REPRODUCE.md). All RAW decoding in the provided auditor uses LibRaw/rawpy; testing another independent decoder would be additional evidence.

The data and generated contact sheet are synthetic research materials under the repository's GPL-3.0-only terms. No rights in Nikon's format or third-party material are claimed. These files are not firmware or an installation image.
