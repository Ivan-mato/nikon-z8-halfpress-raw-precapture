# SPDX-License-Identifier: GPL-3.0-only
"""Independent read-only exFAT/TIFF parsing and complete LibRaw CFA comparison.

Imports no delivered audit helper. Never repairs a NEF or writes the card.
"""
from pathlib import Path
import hashlib, io, json, math, re, struct, sys, time
import numpy as np
import rawpy
from PIL import Image


def digest(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f,'sha256').hexdigest()

class Card:
    def __init__(self,path):
        self.f=Path(path).open('rb'); self.size=Path(path).stat().st_size
        mbr=self.read(0,512)
        assert mbr[510:]==b'\x55\xaa'
        self.base=struct.unpack_from('<I',mbr,454)[0]*512
        boot=self.read(self.base,512)
        assert boot[3:11]==b'EXFAT   '
        self.sector=1<<boot[108]; self.cluster=self.sector<<boot[109]
        self.fat,self.fatlen,self.heap,self.count,self.root=struct.unpack_from('<IIIII',boot,80)
        assert self.base+self.heap*self.sector+self.count*self.cluster<=self.size
        self.rows=[]; self.directories=set()
        self.walk(self.root,'')
    def read(self,offset,n):
        assert 0<=offset<=self.size and 0<=n<=self.size-offset
        self.f.seek(offset); data=self.f.read(n); assert len(data)==n
        return data
    def blocks(self,start,length=None,contiguous=False):
        seen=set(); left=length; current=start
        while current<0xfffffff8 and (left is None or left>0):
            assert 2<=current<self.count+2 and current not in seen
            seen.add(current)
            n=self.cluster if left is None else min(left,self.cluster)
            yield self.read(self.base+self.heap*self.sector+(current-2)*self.cluster,n)
            if left is not None:
                left-=n
                if left==0: break
            current=current+1 if contiguous else struct.unpack('<I',self.read(self.base+self.fat*self.sector+current*4,4))[0]
        assert left in (None,0), 'truncated chain'
    def walk(self,start,prefix,length=None,contiguous=False):
        assert start not in self.directories and len(self.directories)<64
        self.directories.add(start)
        chunks=[]
        for b in self.blocks(start,length,contiguous):
            chunks.append(b); assert sum(map(len,chunks))<=16*1024*1024
        data=b''.join(chunks); pos=0
        while pos+32<=len(data):
            t=data[pos]
            if t==0: return
            if t!=0x85: pos+=32; continue
            n=data[pos+1]; assert 2<=n<=18
            group=data[pos:pos+32*(n+1)]; assert len(group)==32*(n+1)
            checksum=0
            for i,x in enumerate(group):
                if i not in (2,3): checksum=(((checksum>>1)|((checksum&1)<<15))+x)&65535
            assert checksum==struct.unpack_from('<H',group,2)[0] and group[32]==0xc0
            name=b''.join(group[i+2:i+32] for i in range(64,len(group),32) if group[i]==0xc1)[:group[35]*2].decode('utf-16le')
            assert name and '/' not in name and name not in ('.','..')
            size=struct.unpack_from('<Q',group,56)[0]; valid=struct.unpack_from('<Q',group,40)[0]
            row=dict(path=prefix+name,bytes=size,valid_bytes=valid,first_cluster=struct.unpack_from('<I',group,52)[0],
                contiguous=bool(group[33]&2),directory=bool(struct.unpack_from('<H',group,4)[0]&16))
            self.rows.append(row)
            if row['directory']: self.walk(row['first_cluster'],row['path']+'/',size,row['contiguous'])
            pos+=len(group)
    def file_hash(self,row):
        assert row['bytes']==row['valid_bytes'] and not row['directory']
        h=hashlib.sha256()
        for b in self.blocks(row['first_cluster'],row['bytes'],row['contiguous']): h.update(b)
        return h.hexdigest()

def structure(data):
    assert data[:4]==b'II*\0'
    sizes={1:1,2:1,3:2,4:4,5:8,6:1,7:1,8:2,9:4,10:8,11:4,12:8,13:4}
    def directory(off,base=0,lo=0,hi=None):
        hi=len(data) if hi is None else hi
        assert lo<=off<=hi-2
        n=struct.unpack_from('<H',data,off)[0]; assert n<1024 and off+6+12*n<=hi
        tags={}
        for i in range(n):
            p=off+2+i*12; tag,kind,count,value=struct.unpack_from('<HHII',data,p)
            assert kind in sizes and tag not in tags
            length=sizes[kind]*count; where=p+8 if length<=4 else base+value
            assert lo<=where<=hi and length<=hi-where
            tags[tag]=(kind,count,data[where:where+length],where)
        return tags,struct.unpack_from('<I',data,off+2+12*n)[0]
    def ints(tags,key):
        kind,n,blob,_=tags[key]; assert kind in (3,4,13) and 0<n<1024
        return struct.unpack('<'+('H' if kind==3 else 'I')*n,blob)
    def one(tags,key):
        values=ints(tags,key); assert len(values)==1
        return values[0]
    queue=[struct.unpack_from('<I',data,4)[0]]; seen=set(); ifds=[]
    while queue:
        address=queue.pop(0)
        if not address: continue
        assert address not in seen and len(seen)<32
        seen.add(address); tags,nxt=directory(address); ifds.append(tags)
        queue.append(nxt)
        if 330 in tags: queue.extend(ints(tags,330))
    assert ifds[0][272][2].rstrip(b'\0')==b'NIKON Z 8'
    raw=[t for t in ifds if 262 in t and one(t,262)==32803]
    assert len(raw)==1
    t=raw[0]; w,h,bits,compression=[one(t,k) for k in (256,257,258,259)]
    assert (w,h,bits,compression)==(8280,5520,14,34713)
    off,length=one(t,273),one(t,279)
    assert length>0 and off+length<=len(data)
    assert length not in [math.ceil(w*14*c/8/16)*16*h for c in (1,3)]
    exif,_=directory(one(ifds[0],0x8769)); maker=exif[0x927c]
    assert maker[0]==7 and maker[2][:10]==b'Nikon\0\x02\x11\0\0'
    base=maker[3]+10; end=maker[3]+len(maker[2]); assert data[base:base+4]==b'II*\0'
    note,_=directory(base+struct.unpack_from('<I',data,base+4)[0],base,maker[3],end)
    assert note[0x96][2].startswith(b'F0'+struct.pack('<4H',2048,2048,2048,2048))
    previews=[]
    for t in ifds:
        if 513 not in t and 514 not in t: continue
        o,n=one(t,513),one(t,514); assert n>0 and o+n<=len(data)
        jpeg=data[o:o+n]; assert jpeg.startswith(b'\xff\xd8') and jpeg.endswith(b'\xff\xd9')
        with Image.open(io.BytesIO(jpeg)) as image:
            assert image.format=='JPEG'; image.load(); previews.append(list(image.size))
    assert sorted(previews)==[[160,120],[1620,1080],[8256,5504]]
    return dict(width=w,height=h,bits=bits,compression=compression,strip_offset=off,strip_bytes=length,
                strip_sha256=hashlib.sha256(data[off:off+length]).hexdigest(),previews=previews,packed_fallback_excluded=True)

def compare(nef,source):
    with source.open('rb') as f: header=f.read(32)
    magic,sw,sh,bits,cfa,black,white=struct.unpack('<8s6I',header)
    assert magic==b'NZ9RAW1\0' and (bits,cfa,black,white)==(14,0,0,16383)
    assert sw%2==0 and sh%2==0 and source.stat().st_size==32+sw*sh*2
    src=np.memmap(source,dtype='<u2',mode='r',offset=32,shape=(sh,sw))
    assert src.max()<=16383
    with rawpy.imread(str(nef)) as r:
        pixels=r.raw_image
        assert pixels.shape==(5520,8280) and pixels.dtype==np.uint16
        h,w=pixels.shape; x=np.arange(w); y=np.arange(h)
        sx=2*((x//2)*(sw//2)//(w//2))+(x%2)
        sy=2*((y//2)*(sh//2)//(h//2))+(y%2)
        count=0; mismatches=0; digest_=hashlib.sha256()
        for start in range(0,h,64):
            actual=pixels[start:start+64]
            expected=src[sy[start:start+64,None],sx[None,:]]
            mismatches+=int(np.count_nonzero(actual!=expected)); count+=actual.size
            digest_.update(actual.astype('<u2',copy=False).tobytes())
        assert count==45705600 and pixels.max()<=16383
        result=dict(samples=count,mismatches=mismatches,minimum=int(pixels.min()),maximum=int(pixels.max()),
            decoded_sha256=digest_.hexdigest(),source_sha256=digest(source),source_geometry=[sw,sh])
        assert mismatches==0, result
        return result
