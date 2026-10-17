# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Compile the actual rearm and RAW-port functions against bounded test state."""
from pathlib import Path
import os
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / 'qemu/nikon-z8-lab.c').read_text()


def function(name):
    start = source.index('static bool ' + name + '(')
    end = source.index('\n}\n', start) + 3
    return source[start:end]


prelude = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <inttypes.h>
#include <stdio.h>
#include <string.h>
typedef uint64_t hwaddr;
typedef struct {
    uint32_t descriptors[10], frame_pending;
    uint64_t descriptor_writes;
} Port;
typedef struct {
    bool capture_stream_rearm_model, engine1543_held[3];
    uint64_t capture_nv16_jobs;
    bool capture_nv16_requested, capture_nv16_failed;
    uint32_t engine1542_pending[12];
    struct { uint32_t pending; } engine1518[3];
    uint64_t capture_nv16_jpeg_consumed[3];
    bool engine1540_alternate_bank_model, engine1540_descriptors_model;
    Port raw_transport[2];
} NikonZ8State;
static unsigned faults;
static void unknown_access(NikonZ8State *s, hwaddr addr, uint64_t value,
                           unsigned size, bool write)
{ (void)s; (void)addr; (void)value; (void)size; (void)write; faults++; }
'''
main = r'''
int main(void) {
    NikonZ8State good = {0}, s, before;
    good.capture_stream_rearm_model = true;
    good.engine1543_held[1] = true;
    good.capture_nv16_jobs = 2;
    for (unsigned i=0;i<3;i++) { good.capture_nv16_jpeg_consumed[i]=2; }
    before=good; assert(capture_stream_can_rearm(&good,1));
    assert(!memcmp(&before,&good,sizeof good));
    assert(!capture_stream_can_rearm(&good,0));
    assert(!capture_stream_can_rearm(&good,2));
    s=good; s.capture_stream_rearm_model=false; assert(!capture_stream_can_rearm(&s,1));
    s=good; s.engine1543_held[1]=false; assert(!capture_stream_can_rearm(&s,1));
    s=good; s.capture_nv16_jobs=0; assert(!capture_stream_can_rearm(&s,1));
    s=good; s.capture_nv16_requested=true; assert(!capture_stream_can_rearm(&s,1));
    s=good; s.capture_nv16_failed=true; assert(!capture_stream_can_rearm(&s,1));
    for (unsigned bit=0;bit<32;bit++) {
        s=good; s.engine1542_pending[1]=1u<<bit; assert(!capture_stream_can_rearm(&s,1));
        s=good; s.engine1542_pending[11]=1u<<bit; assert(!capture_stream_can_rearm(&s,1));
        s=good; s.engine1518[0].pending=1u<<bit; assert(!capture_stream_can_rearm(&s,1));
    }
    for (unsigned i=0;i<3;i++) {
        // Downstream JPEG completion is independent of receiver ownership.
        s=good; s.capture_nv16_jpeg_consumed[i]=1; assert(capture_stream_can_rearm(&s,1));
    }
    s=(NikonZ8State){0}; s.engine1540_descriptors_model=true;
    assert(!engine1540_descriptor_write(&s,0x153c01a8,0xff,4));
    assert(faults==0 && s.raw_transport[0].descriptor_writes==0);
    assert(engine1540_descriptor_write(&s,0x154001a8,0xff,4));
    s.engine1540_alternate_bank_model=true;
    assert(engine1540_descriptor_write(&s,0x153c01a8,0xabc,4));
    uint64_t read=0;
    assert(engine1540_descriptor_read(&s,0x153c01a8,4,&read) && read==0xabc);
    assert(engine1540_descriptor_read(&s,0x154001a8,4,&read) && read==0xff);
    assert(!engine1540_descriptor_read(&s,0x153c01cc,4,&read));
    before=s;
    const struct { hwaddr addr; uint64_t value; unsigned size; } bad[] = {
        {0x153c01a8,0x1000,4}, {0x153c01a4,1,4},
        {0x153c01a8,0xff,8}, {0x153c01a9,0,4},
    };
    for (unsigned i=0;i<sizeof bad/sizeof bad[0];i++) {
        unsigned old=faults;
        assert(engine1540_descriptor_write(&s,bad[i].addr,bad[i].value,bad[i].size));
        assert(faults==old+1 && !memcmp(&s,&before,sizeof s));
    }
    s.raw_transport[0].frame_pending=0x100; before=s;
    unsigned old=faults;
    assert(engine1540_descriptor_write(&s,0x153c01a8,0,4));
    assert(faults==old+1 && !memcmp(&s,&before,sizeof s));
    puts("PASS completed-receiver rejection, 96 pending-bit cases, bank isolation, strict masks and no mutation on rejection");
    return 0;
}
'''

with tempfile.TemporaryDirectory(prefix='z8-multiframe-contract-') as temp:
    src, exe = Path(temp) / 'test.c', Path(temp) / 'test'
    src.write_text(prelude + '\n'.join(function(name) for name in (
        'capture_stream_can_rearm', 'raw_transport_bank',
        'engine1540_descriptor_address', 'engine1540_descriptor_read',
        'engine1540_descriptor_write')) + main)
    subprocess.run([os.environ.get('CC', 'cc'), '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', str(src), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
