# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Actual RAW compression accepts an older owned buffer and rejects replay."""
from pathlib import Path
import os,re,subprocess,tempfile
ROOT=Path(__file__).resolve().parents[1]
source=(ROOT/'qemu/nikon-z8-lab.c').read_text()
def function(name):
    m=re.search(r'static bool '+name+r'\([^;]*?\n\{',source)
    return source[m.start():source.index('\n}\n',m.start())+3]
def declaration(name):
    start=source.index('typedef struct '+name+' {')
    return source[start:source.index('} '+name+';',start)+len(name)+3]
body=function('raw_transport_bank')+function('engine1540_frame_write')
state_start=source.index('struct NikonZ8State {')
state=source[state_start:source.index('\n};',state_start)]
fields=set()
for name in set(re.findall(r's->(\w+)',body)):
    matches=[line for line in state.splitlines() if re.search(r'\b'+name+r'\b',line) and ';' in line]
    assert len(matches)==1,(name,matches)
    fields.add(matches[0])
prelude=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <inttypes.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
typedef uint64_t hwaddr;
typedef int qemu_irq;
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define MAX(a,b) ((a)>(b)?(a):(b))
#define g_try_malloc malloc
#define g_free free
#define MEMTXATTRS_UNSPECIFIED 0
#define MEMTX_OK 0
''' + declaration('Z8OwnedRaw')+declaration('Ex7RawTransport')+r'''
typedef struct {
'''+'\n'.join(sorted(fields))+r'''
} NikonZ8State;
static uint8_t input[64],output[64];
static unsigned faults,writes,irqs;
static int address_space_memory;
static bool dma_ram_range(NikonZ8State *s,uint64_t a,uint64_t n)
{ (void)s;return (a==UINT64_C(0x850000000)||a==UINT64_C(0x860000000)) && n<=64; }
static int address_space_read(int *m,uint64_t a,int flags,void *p,size_t n)
{ (void)m;(void)flags;memcpy(p,a==UINT64_C(0x850000000)?input:output,n);return 0; }
static int address_space_write(int *m,uint64_t a,int flags,const void *p,size_t n)
{ (void)m;(void)flags;assert(a==UINT64_C(0x860000000));memcpy(output,p,n);writes++;return 0; }
static void unknown_access(NikonZ8State *s,hwaddr a,uint64_t v,unsigned n,bool write)
{ (void)s;(void)a;(void)v;(void)n;(void)write;faults++; }
static void engine1540_frame_update_irq(NikonZ8State *s,unsigned b)
{ assert(writes && s->raw_transport[b].frame_pending==0x100);irqs++; }
'''
main=r'''
int main(void) {
    NikonZ8State s={0};
    s.engine1540_frame_pass_model=s.engine1540_alternate_bank_model=true;
    s.primary_d980_packed14_model=true;s.primary_d980_cache_format=1;
    s.primary_d980_frames=7;s.engine151_raw_output_frame=3;s.engine151_raw_output_jobs=3;
    s.engine151_raw_output_target=UINT64_C(0x880000000);
    s.engine151_config[0][0x4a0/4]=4|(2<<16);s.engine151_config[0][0x4d0/4]=32;
    Z8OwnedRaw r={.generation=2,.address=UINT64_C(0x850000000),.bytes=64,
        .width=4,.height=2,.stride=32,.format=1,.processed=true};
    int slot=raw_owned_slot(s.capture_raw_side,64,&r);assert(slot>=0);
    raw_owned_publish(s.capture_raw_side,64,&r,slot);
    assert(raw_owned_slot(s.capture_raw_side,64,&r)<0);
    for(unsigned b=0;b<2;b++) {
        uint32_t *p=s.raw_transport[b].parameters;
        p[0x400/4]=0x50000000;p[0x404/4]=8;
        p[0x420/4]=0x60000000;p[0x424/4]=8;
        p[0x408/4]=p[0x428/4]=32;p[0x4c/4]=4;p[0x50/4]=2;
        p[0x40/4]=0x10001;p[0xd4/4]=64;
        for(unsigned i=0;i<10;i++)s.raw_transport[b].descriptors[i]=i%5==0?2:i%5==1?255:0;
    }
    assert(engine1540_frame_write(&s,0x153c0008,1,4));
    assert(!faults && writes==1 && irqs==1 && s.raw_transport[0].frame_frame==2);
    assert(s.capture_raw_side[slot].consumed && s.raw_transport[0].frame_result_bytes>0);
    // Even after IRQ acknowledgment, the other bank cannot consume the same RAM generation.
    assert(engine1540_frame_write(&s,0x15400008,1,4));
    assert(faults==1 && writes==1 && irqs==1);
    r.generation=8;slot=raw_owned_slot(s.capture_raw_side,64,&r);assert(slot>=0);
    raw_owned_publish(s.capture_raw_side,64,&r,slot);
    s.engine151_capture_pending=true; // A different producer's IRQ does not own this older buffer.
    assert(engine1540_frame_write(&s,0x15400008,1,4));
    assert(faults==1 && writes==2 && irqs==2 && s.raw_transport[1].frame_frame==8);
    assert(raw_owned_find(s.capture_raw_side,64,r.address,6,2,32,1)<0);
    // No unseen record can be invented from the latest input counter.
    memset(s.capture_raw_side,0,sizeof s.capture_raw_side);s.raw_transport[1].frame_pending=0;s.raw_transport[0].frame_pending=0;
    assert(engine1540_frame_write(&s,0x153c0008,1,4));
    assert(faults==2 && writes==2 && irqs==2);
    r.generation=9;r.processed=false;
    slot=raw_owned_slot(s.capture_raw_side,64,&r);
    raw_owned_publish(s.capture_raw_side,64,&r,slot);
    assert(engine1540_frame_write(&s,0x153c0008,1,4));
    assert(faults==3 && writes==2 && irqs==2); // Producer's own IRQ has not been ACKed.
    s.capture_raw_side[slot].processed=true;
    assert(engine1540_frame_write(&s,0x153c0008,1,4));
    assert(faults==3 && writes==3 && irqs==3 && s.raw_transport[0].frame_frame==9);
    puts("PASS actual RAW codec: older owned frame, real bytes/readback before IRQ, duplicate and unknown buffer rejection");
}
'''
with tempfile.TemporaryDirectory(prefix='z8-raw-owner-') as temp:
    src,exe=Path(temp)/'test.c',Path(temp)/'test'
    src.write_text(prelude+(ROOT/'qemu/nikon-z8-owned-raw.h').read_text()+
        (ROOT/'qemu/nikon-z8-lossless.h').read_text()+body+main)
    subprocess.run([os.environ.get('CC','cc'),'-Wall','-Wextra','-Werror',
        '-fsanitize=address,undefined',str(src),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
