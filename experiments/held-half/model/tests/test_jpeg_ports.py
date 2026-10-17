# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Exercise the actual JPEG MMIO handlers with independent port state."""
from pathlib import Path
import os
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / 'qemu/nikon-z8-lab.c').read_text()


def function(name):
    match = re.search(r'static [^\n]*\b' + name + r'\([^;]*?\)\n\{', source)
    assert match, name
    return source[match.start():source.index('\n}\n', match.start()) + 3]


prelude = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include <stdio.h>
typedef struct {
    int irq;
    bool requested, result_valid, deferred_failed;
    uint32_t pending, core;
    uint64_t capacity, last_bytes;
    unsigned height;
} Port;
typedef struct {
    bool engine15e2_jpeg_model, engine15e2_alternate_bank_model;
    bool engine15e2_result474_model, engine15e2_deferred_input_model;
    Port jpeg_ports[2];
    uint32_t engine15e2_config[2][0x500/4];
    uint64_t engine15e2_jpeg_acks, engine15e2_jpeg_core_acks;
    uint64_t engine15e2_jpeg_requests, engine15e2_deferred_waits;
    uint64_t engine15e2_idle_resets[2];
} NikonZ8State;
static unsigned faults;
static uint64_t last_fault;
static int lines[3];
static void qemu_set_irq(int irq, int value) { lines[irq]=value; }
static void unknown_access(NikonZ8State *s,uint64_t a,uint64_t v,unsigned z,bool w)
{ (void)s;(void)v;(void)z;(void)w;faults++;last_fault=a; }
/* No producer exists in this harness. Starting/encoding must be rejected. */
static bool engine15e2_jpeg_request(NikonZ8State *s,unsigned b)
{ (void)s;(void)b;return false; }
static bool engine15e2_jpeg_source_ready(NikonZ8State *s,unsigned b)
{ (void)s;(void)b;return false; }
static bool engine15e2_limit_disabled_request(NikonZ8State *s,unsigned b)
{ (void)s;(void)b;return false; }
static bool engine15e2_jpeg_pixels(NikonZ8State *s,unsigned b)
{ (void)s;(void)b;assert(!"codec must not run without a producer");return false; }
'''
main = r'''
int main(void) {
    NikonZ8State s={0},before;
    s.engine15e2_jpeg_model=true;
    s.jpeg_ports[0].irq=1;s.jpeg_ports[1].irq=2;
    assert(!engine15e2_jpeg_write(&s,1,4,1,4));
    s.engine15e2_alternate_bank_model=true;
    s.engine15e2_config[0][0x484/4]=0x800c000;
    s.engine15e2_config[1][0x484/4]=0x800c000;
    for(unsigned b=0;b<2;b++) {
        s.jpeg_ports[b].pending=0x800c000;
        s.jpeg_ports[b].core=0x80000000;
        s.jpeg_ports[b].result_valid=true;
        s.jpeg_ports[b].last_bytes=100+b;
        s.jpeg_ports[b].height=500+b;
    }
    engine15e2_jpeg_irq_update(&s);assert(lines[1] && lines[2]);
    uint64_t v=0;
    assert(engine15e2_jpeg_read(&s,0,0x20,4,&v) && v==100);
    assert(engine15e2_jpeg_read(&s,1,0x20,4,&v) && v==101);
    assert(engine15e2_jpeg_write(&s,1,0x480,0x800c000,4));
    assert(lines[1] && !lines[2] && s.jpeg_ports[0].pending==0x800c000);
    assert(engine15e2_jpeg_write(&s,1,0x2c,0x7fffffff,4));
    assert(s.jpeg_ports[0].core==0x80000000 && !s.jpeg_ports[1].core);
    assert(engine15e2_jpeg_write(&s,1,4,0x80000000,4));
    assert(!s.jpeg_ports[1].result_valid && s.jpeg_ports[0].result_valid);
    before=s;
    const struct {unsigned bank,off,size;uint64_t value;} bad[]={
        {0,0x480,4,1},{0,0x480,8,0x800c000},
        {0,0x2c,4,0x80000000},{0,4,4,0x80000000},
        {1,4,4,1},{1,0x400,4,0x4000},{1,0x404,4,0x4000},
    };
    for(unsigned i=0;i<sizeof bad/sizeof bad[0];i++) {
        unsigned n=faults;
        assert(engine15e2_jpeg_write(&s,bad[i].bank,bad[i].off,bad[i].value,bad[i].size));
        assert(faults==n+1 && last_fault==0x15e20000+bad[i].bank*0x1000+bad[i].off);
        assert(!memcmp(&s,&before,sizeof s));
    }
    s.engine15e2_result474_model=true;
    unsigned n=faults;
    assert(engine15e2_jpeg_read(&s,1,0x474,4,&v) && faults==n+1);
    assert(engine15e2_jpeg_read(&s,0,0x474,4,&v) && v==100);
    puts("PASS JPEG port isolation, IRQ masks, W1C/core ACK, actual result visibility and rejected starts/resets");
    return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='z8-jpeg-ports-') as temp:
    p=Path(temp)/'test.c'
    p.write_text(prelude+'\n'.join(function(n) for n in (
        'engine15e2_jpeg_irq_update','engine15e2_jpeg_read','engine15e2_jpeg_write'))+main)
    exe=Path(temp)/'test'
    subprocess.run([os.environ.get('CC','cc'),'-Wall','-Wextra','-Werror',
                    '-fsanitize=address,undefined',str(p),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
