# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Exercise actual 153 request/DMA/IRQ code with deterministic RAM."""
from pathlib import Path
import os
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / 'qemu/nikon-z8-lab.c').read_text()


def function(name):
    match = re.search(r'static (?:bool|void) ' + name + r'\([^;]*?\n\{', source)
    end = source.index('\n}\n', match.start()) + 3
    return source[match.start():end]


prelude = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <inttypes.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#define MiB (1024*1024)
#define MAX(a,b) ((a)>(b)?(a):(b))
#define MEMTXATTRS_UNSPECIFIED 0
#define MEMTX_OK 0
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define g_malloc malloc
#define g_free free
typedef uint64_t hwaddr;
typedef struct {
    uint64_t generation,address,bytes;
    unsigned width,height,stride,format;
    bool processed,consumed;
} Z8OwnedRaw;
typedef struct {
    Z8OwnedRaw capture_raw_input[64];
    bool engine153_config_model, engine153_inplace_identity_model;
    bool engine153_frame_pass_model, engine153_alternate_bank_model;
    uint32_t engine153_config[2][0x150/4], engine153_pending[2];
    bool engine153_requested[2], engine153_failed[2];
    uint64_t engine153_expected_frame[2];
    uint8_t engine153_descriptor_snapshot[2][0x7c0];
    uint64_t engine153_identity_hash, engine153_consumed_dma_frame[2];
    uint64_t engine153_jobs[2], engine153_bytes[2], engine153_acks[2];
    uint64_t engine153_last_source[2], engine153_last_target[2];
    uint64_t engine153_config_writes[2], engine153_reset_pulses[2];
    int *engine153_irq[2];
    uint64_t primary_d980_frames, primary_d980_last_physical;
    uint8_t *primary_d980_cache;
    unsigned primary_d980_cache_width, primary_d980_cache_height;
    unsigned primary_d980_cache_stride, primary_d980_cache_format;
    bool primary_d980_packed14_model;
} NikonZ8State;
static unsigned faults, reads, writes;
static uint8_t descriptor[0x7c0], pixels[64];
static int address_space_memory, irqs[2];
static void qemu_set_irq(int *irq, int value) { *irq=!!value; }
static void unknown_access(NikonZ8State *s, hwaddr a, uint64_t v, unsigned n, bool w)
{ (void)s; (void)a; (void)v; (void)n; (void)w; faults++; }
static bool dma_ram_range(NikonZ8State *s, uint64_t a, size_t n)
{ (void)s; return (a==UINT64_C(0xa00010000) && n==sizeof descriptor) ||
    ((a==UINT64_C(0x8a0000000) || a==UINT64_C(0x8b0000000)) && n==64); }
static uint32_t ldl_le_p(const uint8_t *p)
{ return (uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24; }
static int address_space_read(int *m,uint64_t a,int attr,void *p,size_t n)
{ (void)m; (void)attr; if(a==UINT64_C(0xa00010000)) memcpy(p,descriptor,n);
  else { memcpy(p,pixels,n); reads++; } return 0; }
static int address_space_write(int *m,uint64_t a,int attr,const void *p,size_t n)
{ (void)m; (void)a; (void)attr; assert(n==64 && !memcmp(p,pixels,n)); writes++; return 0; }
'''
main = r'''
static NikonZ8State initial(void) {
    NikonZ8State s={0};
    s.engine153_config_model=s.engine153_inplace_identity_model=true;
    s.engine153_alternate_bank_model=s.primary_d980_packed14_model=true;
    s.primary_d980_cache=pixels; s.primary_d980_frames=1;
    s.primary_d980_cache_width=4; s.primary_d980_cache_height=2;
    s.primary_d980_cache_stride=32; s.primary_d980_cache_format=1;
    s.primary_d980_last_physical=UINT64_C(0x8a0000000);
    s.capture_raw_input[0]=(Z8OwnedRaw){.generation=1,.address=s.primary_d980_last_physical,
        .bytes=64,.width=4,.height=2,.stride=32,.format=1};
    memset(descriptor,0,sizeof descriptor);
    descriptor[0]=1; descriptor[4]=32; descriptor[0x90]=4; descriptor[0x92]=2;
    memset(pixels,0x71,sizeof pixels);
    for(unsigned b=0;b<2;b++) {
        uint32_t *c=s.engine153_config[b];
        c[0x44/4]=c[0x74/4]=c[0x94/4]=1;
        c[0x48/4]=0x10000; c[0x4c/4]=10;
        c[0xb0/4]=8; c[0xb4/4]=b?0xa0000000:0xb0000000;
        c[0x20/4]=1; s.engine153_irq[b]=&irqs[b]; irqs[b]=0;
    }
    return s;
}
static void start(NikonZ8State *s,unsigned b)
{ assert(engine153_config_write(s,b?0x15380004:0x15340004,1,4)); }
int main(void) {
    NikonZ8State s=initial(), before;
    start(&s,1); assert(s.engine153_jobs[1]==1 && irqs[1] && writes==1);
    assert(engine153_config_write(&s,0x1538002c,1,4));
    assert(!irqs[1] && !s.engine153_config[1][1]);
    start(&s,0); assert(s.engine153_requested[0] && !irqs[0] && writes==1);
    assert(s.engine153_expected_frame[0]==2 && !s.engine153_pending[0]);
    before=s; unsigned old=faults;
    start(&s,0);
    assert(engine153_config_write(&s,0x153400b4,0xa0000000,4));
    assert(engine153_config_write(&s,0x15340000,1,4));
    assert(engine153_config_write(&s,0x1534002c,1,4));
    assert(faults==old+4 && !memcmp(&s,&before,sizeof s));
    s.primary_d980_frames=2; s.primary_d980_last_physical=UINT64_C(0x8b0000000);
    s.capture_raw_input[1]=(Z8OwnedRaw){.generation=2,.address=s.primary_d980_last_physical,
        .bytes=64,.width=4,.height=2,.stride=32,.format=1};
    memset(pixels,0xa2,sizeof pixels); engine153_source_arrived(&s);
    assert(!s.engine153_requested[0] && s.engine153_jobs[0]==1);
    assert(s.engine153_consumed_dma_frame[0]==2 && irqs[0] && writes==2 && reads==2);
    before=s; engine153_source_arrived(&s); assert(!memcmp(&s,&before,sizeof s) && writes==2);
    for(unsigned kind=0;kind<3;kind++) {
        s=initial(); start(&s,0); unsigned n=writes; old=faults;
        s.primary_d980_frames=kind==2?3:2;
        s.primary_d980_last_physical=kind==0?UINT64_C(0x8a0000000):UINT64_C(0x8b0000000);
        s.capture_raw_input[1]=(Z8OwnedRaw){.generation=s.primary_d980_frames,
            .address=s.primary_d980_last_physical,.bytes=64,.width=4,.height=2,.stride=32,.format=1};
        if(kind==1) descriptor[0x200]=1;
        engine153_source_arrived(&s);
        assert(s.engine153_failed[0] && s.engine153_requested[0]);
        assert(faults==old+1 && writes==n && !irqs[0] && !s.engine153_jobs[0]);
        engine153_source_arrived(&s); assert(faults==old+1);
    }
    s=initial(); s.engine153_alternate_bank_model=false; before=s; old=faults;
    start(&s,0); assert(faults==old+1 && !memcmp(&s,&before,sizeof s));
    puts("PASS RAW wait: no stale DMA/IRQ, immutable ownership, exact generation/address/descriptor and strict default");
}
'''

with tempfile.TemporaryDirectory(prefix='z8-raw-wait-') as temp:
    src, exe = Path(temp) / 'test.c', Path(temp) / 'test'
    raw_header=(ROOT/'qemu/nikon-z8-owned-raw.h').read_text()
    find=raw_header[:raw_header.index('static bool raw_owned_overlap')]
    src.write_text(prelude + find + '\n'.join(function(name) for name in (
        'engine153_irq_update', 'engine153_frame_pass', 'engine153_source_arrived',
        'engine153_config_register', 'engine153_config_write')) + main)
    subprocess.run([os.environ.get('CC', 'cc'), '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', str(src), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
