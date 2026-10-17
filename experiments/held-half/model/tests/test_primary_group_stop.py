# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Actual primary MMIO stop/read/IRQ handlers, with external DMA already drained."""
from pathlib import Path
import os
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / 'qemu/nikon-z8-lab.c').read_text()


def function(name):
    match = re.search(r'static (?:bool|void|uint32_t) ' + name + r'\([^;]*?\n\{', source)
    return source[match.start():source.index('\n}\n', match.start()) + 3]


body = '\n'.join(function(n) for n in (
    'engine150c_stop_causes', 'engine150c_stop_command',
    'engine150c_stop_irq_update', 'engine150c_stop_read',
    'primary_direct_map', 'engine150c_stop_write'))
table_start = source.index('static const struct { uint32_t engine, cause; unsigned group; } primary_direct_stops[]')
table = source[table_start:source.index('\n};', table_start) + 3]
# Select the original declarations, so counter widths/register dimensions
# cannot silently diverge from the model under test.
state_start = source.index('struct NikonZ8State {')
state = source[state_start:source.index('\n};', state_start)]
declarations = set()
for field in set(re.findall(r's->(\w+)', body)):
    matches = [line for line in state.splitlines()
               if re.search(r'\b' + field + r'\b', line) and ';' in line]
    assert len(matches) == 1, (field, matches)
    declarations.add(matches[0])
prelude = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <inttypes.h>
#include <stdio.h>
#include <string.h>
typedef uint64_t hwaddr;
typedef int *qemu_irq;
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define HWADDR_PRIx PRIx64
typedef struct { int cpu_index; struct { uint64_t pc; } env; } CPU;
static CPU *current_cpu;
#define ARM_CPU(c) (c)
typedef struct {
''' + '\n'.join(sorted(declarations)) + r'''
} NikonZ8State;
static unsigned faults;
static void qemu_set_irq(qemu_irq irq, int level) { *irq=!!level; }
static void statistics_update(NikonZ8State *s) { (void)s; }
static void primary_empty_end_update(NikonZ8State *s) { (void)s; }
static void primary_d980_single_cancel(NikonZ8State *s) { s->primary_d980_single_armed=false; }
static bool primary_bounded_reset_write(NikonZ8State *s,hwaddr a,uint64_t v,unsigned n)
{ (void)s;(void)a;(void)v;(void)n;return false; }
static void unknown_access(NikonZ8State *s,hwaddr a,uint64_t v,unsigned n,bool w)
{ (void)s;(void)a;(void)v;(void)n;(void)w;faults++; }
'''
main = r'''
static NikonZ8State initial(int *irq) {
    NikonZ8State s={0};
    s.engine150c_stop_model=s.primary_capture_direct_stop_model=true;
    s.primary_capture_group_stop_model=s.primary_d980_stream_model=true;
    s.raw_pipeline_model=s.primary_parameter_control_model=true;
    s.engine150c_active=s.engine150c_latched=0x401e;
    s.primary_d980_single_epoch=s.primary_d980_input_epoch=7;
    s.primary_d980_frames=1;s.engine150c_irq=irq;
    s.engine_150c_init[0x30/4]=0x100;
    *irq=0;return s;
}
int main(void) {
    int irq;uint64_t v;NikonZ8State s=initial(&irq),before;
    assert(engine150c_stop_write(&s,0x150c000c,0x401e,4));
    assert(!faults && !irq && !s.engine150c_active);
    assert(s.engine150c_direct_stop_pending==0x400 && !s.engine150c_direct_stop_pending1);
    assert(s.engine150c_direct_stop_done==0x401e && s.engine150c_latched==0x401e);
    assert(s.primary_d980_frames==1); // Drain never fabricates another input.
    assert(engine150c_stop_read(&s,0x150c0204,4,&v) && !v);
    assert(engine150c_stop_read(&s,0x150c0208,4,&v) && v==0x400);
    s.engine_150c_init[0x200/4]=0x400;engine150c_stop_irq_update(&s);assert(irq);
    before=s;unsigned old=faults;
    assert(engine150c_stop_write(&s,0x150c000c,0x401e,4));
    assert(faults==old+1 && !memcmp(&before,&s,sizeof s));
    assert(engine150c_stop_write(&s,0x150c0204,0,4) && irq);
    assert(engine150c_stop_write(&s,0x150c0204,0x400,4));
    assert(!irq && !s.engine150c_direct_stop_done && !s.engine150c_latched);
    assert(s.engine150c_direct_stop_acks==1 && s.primary_d980_frames==1);
    assert(engine150c_stop_write(&s,0x150c0204,0x400,4));
    assert(s.engine150c_direct_stop_acks==1);
    for(unsigned kind=0;kind<6;kind++) {
        s=initial(&irq);
        if(kind==0)s.primary_d980_frames=0;
        if(kind==1)s.primary_d980_single_armed=true;
        if(kind==2)s.event_pending_1508=1;
        if(kind==3)s.primary_d980_input_epoch++;
        if(kind==4)s.engine150c_active&=~2;
        if(kind==5)s.engine_150c_init[0x18/4]=2;
        before=s;old=faults;
        assert(engine150c_stop_write(&s,0x150c000c,0x401e,4));
        assert(faults==old+1 && !memcmp(&before,&s,sizeof s) && !irq);
    }
    s=initial(&irq);s.primary_capture_group_stop_model=false;
    assert(engine150c_stop_write(&s,0x150c000c,0x401e,4));
    assert(s.engine150c_direct_stop_pending==0x4108000);
    assert(s.engine150c_direct_stop_pending1==0x4000020);
    before=s;old=faults;
    assert(engine150c_stop_write(&s,0x150c0204,0x400,4));
    assert(faults==old+1 && !memcmp(&before,&s,sizeof s));
    s=initial(&irq);s.engine150c_active=s.engine150c_latched=0x30000;
    assert(engine150c_stop_write(&s,0x150c000c,0x30000,4));
    assert(s.engine150c_direct_stop_pending==0x420000); // Other bank unchanged.
    puts("PASS actual primary stop: DMA/channel prerequisites, mask/raw views, W1C ownership, strict legacy and unrelated bank");
}
'''
with tempfile.TemporaryDirectory(prefix='z8-primary-stop-') as temp:
    src, exe = Path(temp)/'test.c', Path(temp)/'test'
    src.write_text(prelude + table + body + main)
    subprocess.run([os.environ.get('CC', 'cc'), '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', str(src), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
