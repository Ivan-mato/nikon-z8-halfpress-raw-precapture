# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Producer history survives overlapping frame/JPEG task lifetimes."""
from pathlib import Path
import os
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT/'qemu/nikon-z8-lab.c').read_text()
start = source.index('typedef struct Z8OwnedNV16 {')
declaration = source[start:source.index('} Z8OwnedNV16;', start)+len('} Z8OwnedNV16;')]
prelude = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
''' + declaration + r'''
typedef struct {
    bool capture_stream_rearm_model;
    Z8OwnedNV16 capture_owned_nv16[128];
    uint32_t engine15e2_config[2][0x500/4];
} NikonZ8State;
'''
main = r'''
int main(void) {
    NikonZ8State s={.capture_stream_rearm_model=true},before;
    Z8OwnedNV16 a={.generation=1,.y=0x810000000,.uv=0x810100000,
        .width=640,.height=424,.stride=640,.kind=1};
    Z8OwnedNV16 b=a;b.generation=2;b.y+=0x1000000;b.uv+=0x1000000;
    assert(capture_owned_available(&s,&a,1));capture_owned_publish(&s,&a,1);
    assert(capture_owned_available(&s,&b,1));capture_owned_publish(&s,&b,1);
    int first=capture_owned_find(&s,a.y,a.uv,640,424,640,false);
    int second=capture_owned_find(&s,b.y,b.uv,640,424,640,false);
    assert(first>=0 && second>=0 && first!=second);
    assert(s.capture_owned_nv16[first].generation==1);
    uint32_t *c=s.engine15e2_config[1];
    c[0x430/4]=a.y>>4;c[0x434/4]=a.uv>>4;
    c[0x418/4]=640;c[0x41c/4]=424;c[0x410/4]=640;
    assert(capture_owned_jpeg(&s,1)==first); // Old frame remains the owner.
    before=s;Z8OwnedNV16 overlap=b;overlap.y=a.uv+32;
    assert(!capture_owned_available(&s,&overlap,1) && !memcmp(&s,&before,sizeof s));
    s.capture_owned_nv16[first].consumed=true;
    Z8OwnedNV16 replacement=a;replacement.generation=3;
    assert(capture_owned_available(&s,&replacement,1));capture_owned_publish(&s,&replacement,1);
    first=capture_owned_jpeg(&s,1);assert(first>=0 && s.capture_owned_nv16[first].generation==3);
    assert(s.capture_owned_nv16[second].generation==2 && !s.capture_owned_nv16[second].consumed);
    c[0x418/4]=638;assert(capture_owned_jpeg(&s,1)<0);
    Z8OwnedNV16 thumb={.generation=1,.y=0x820000540,.uv=0x820010540,
        .width=160,.height=106,.stride=192,.kind=3};
    capture_owned_publish(&s,&thumb,1);
    assert(capture_owned_find(&s,thumb.y-7*192,thumb.uv-7*192,160,120,192,true)>=0);
    assert(capture_owned_find(&s,thumb.y-7*192,thumb.uv-7*192,160,121,192,true)<0);
    assert(capture_owned_find(&s,thumb.y-7*192,thumb.uv-7*192,160,120,192,false)<0);
    // A full outstanding history cannot be silently recycled.
    for(unsigned i=0;i<128;i++) {
        s.capture_owned_nv16[i]=a;s.capture_owned_nv16[i].generation=i+1;
        s.capture_owned_nv16[i].y+=i*0x200000;s.capture_owned_nv16[i].uv+=i*0x200000;
    }
    assert(!capture_owned_available(&s,&thumb,1));
    s.capture_stream_rearm_model=false;before=s;
    assert(capture_owned_available(&s,&thumb,1));capture_owned_publish(&s,&thumb,1);
    assert(!memcmp(&before,&s,sizeof s));
    puts("PASS actual NV16 history: old JPEG ownership, outstanding-overlap rejection, consumed replacement, thumbnail padding and capacity");
}
'''
with tempfile.TemporaryDirectory(prefix='z8-nv16-history-') as temp:
    src, exe = Path(temp)/'test.c', Path(temp)/'test'
    src.write_text(prelude + (ROOT/'qemu/nikon-z8-owned-nv16.h').read_text() + main)
    subprocess.run([os.environ.get('CC','cc'), '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', str(src), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
