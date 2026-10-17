#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Verify published synthetic NEFs without running or possessing Nikon firmware."""
from pathlib import Path
import argparse,hashlib,json,sys,tempfile,zipfile
import rawpy,numpy
from content import structure,compare,digest

ROOT=Path(__file__).resolve().parents[1]

def main():
    if sys.flags.optimize:
        raise ValueError('Audit assertions require Python without -O')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True,help='New directory outside the repository')
    args=parser.parse_args();out=args.output.resolve()
    assert not out.exists() and not out.is_relative_to(ROOT.parents[1])
    lock=json.loads((ROOT/'source-lock.json').read_text())
    manifest=json.loads((ROOT/'samples/asset-manifest.json').read_text())
    archive=ROOT/'samples'/manifest['file']
    assert digest(archive)==manifest['sha256'] and archive.stat().st_size==manifest['bytes']
    assert digest(ROOT/'synthetic-inputs.zip')==lock['fixture_archive_sha256']
    out.mkdir(parents=True);records=[];negative=None
    with tempfile.TemporaryDirectory(dir=out,prefix='samples-') as temp:
        temp=Path(temp)
        with zipfile.ZipFile(ROOT/'synthetic-inputs.zip') as inputs:
            assert sorted(inputs.namelist())==sorted(lock['fixtures'])
            for name,expected in lock['fixtures'].items():
                data=inputs.read(name);assert hashlib.sha256(data).hexdigest()==expected
                (temp/name).write_bytes(data)
        with zipfile.ZipFile(archive) as z:
            rows=json.loads(z.read('SHA256.json'))
            assert len(rows)==27 and [r['name'] for r in rows]==[f'DSC_{i:04d}.NEF' for i in range(1,28)]
            for i,row in enumerate(rows):
                data=z.read('original-nefs/'+row['name'])
                assert len(data)==row['bytes'] and hashlib.sha256(data).hexdigest()==row['sha256']
                nef=temp/row['name'];nef.write_bytes(data)
                s=structure(data);c=compare(nef,temp/f'frame-{i:02d}.raw')
                assert c['decoded_sha256']==row['decoded_sha256'] and c['source_sha256']==row['source_sha256']
                records.append(dict(name=nef.name,sha256=row['sha256'],structure=s,comparison=c))
                if i==0:
                    try:
                        compare(nef,temp/'frame-01.raw')
                    except AssertionError as error:
                        assert error.args and isinstance(error.args[0],dict)
                        negative=error.args[0];assert negative['mismatches']==45705600
                    else:
                        raise AssertionError('Wrong source unexpectedly accepted')
                nef.unlink()
                print(json.dumps(dict(file=row['name'],mismatches=c['mismatches'])),flush=True)
    assert len({r['comparison']['decoded_sha256'] for r in records})==27
    report=dict(passed=True,scope='Published files only; does not verify their execution provenance',
        files=records,frames=27,total_samples_compared=1234051200,wrong_source_negative_control=negative,
        versions=dict(rawpy=rawpy.__version__,libraw=list(rawpy.libraw_version),numpy=numpy.__version__),
        tool_sha256=digest(Path(__file__)),helper_sha256=digest(ROOT/'scripts/content.py'),archive_sha256=digest(archive),
        producer_samples_compared=False,firmware_execution_performed=False)
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print('PASS 27/27 full-source matches; sample audit only, no firmware execution')

if __name__=='__main__':main()
