# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Actual GPIO request/feedback handlers: pulse ownership and strict IRQ reuse."""
from pathlib import Path
import os,re,subprocess,tempfile

ROOT=Path(__file__).resolve().parents[1]
source=(ROOT/'qemu/nikon-z8-lab.c').read_text()
def function(name):
    match=re.search(r'static (?:bool|void) '+name+r'\([^;]*?\n\{',source)
    return source[match.start():source.index('\n}\n',match.start())+3]
prelude=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint64_t hwaddr;
typedef struct { bool pending; uint64_t at; } Timer;
typedef struct {
    bool ccomp_gpio_model,ccomp_gpio_request,ccomp_gpio_level;
    bool ccomp_gpio_pulse_model,ccomp_gpio_waiting;
    uint64_t ccomp_gpio_requests,ccomp_gpio_responses,ccomp_gpio_requested_frame;
    uint64_t ccomp_gpio_response_delay_ns,primary_d980_frames;
    int *ccomp_gpio_irq;
    Timer *ccomp_gpio_timer;
    uint32_t syscon[0x2000/4],gpio_irq_config[2][8];
} NikonZ8State;
#define QEMU_CLOCK_VIRTUAL 0
static uint64_t now;
static unsigned faults;
static void qemu_set_irq(int *irq,int v) { *irq=!!v; }
static uint64_t qemu_clock_get_ns(int clock) { (void)clock; return now; }
static void timer_mod(Timer *timer,uint64_t at) { timer->pending=true;timer->at=at; }
static void timer_del(Timer *timer) { timer->pending=false; }
static void unknown_access(NikonZ8State *s,hwaddr a,uint64_t v,unsigned n,bool w)
{ (void)s;(void)a;(void)v;(void)n;(void)w;faults++; }
'''
main=r'''
int main(void) {
    NikonZ8State s={0},before;Timer timer={0};int irq=0;
    s.ccomp_gpio_model=true;s.ccomp_gpio_pulse_model=true;
    s.ccomp_gpio_timer=&timer;s.ccomp_gpio_irq=&irq;
    s.ccomp_gpio_response_delay_ns=100000000;
    s.syscon[0x100c/4]=0x234;
    s.gpio_irq_config[0][5]=s.gpio_irq_config[0][6]=0x80;
    now=1000;
    assert(ccomp_gpio_write(&s,0xd15100c,0x10001000,4));
    assert(s.ccomp_gpio_waiting && s.ccomp_gpio_request && timer.at==now+100000000);
    assert(!irq && s.ccomp_gpio_responses==0 && s.syscon[0x100c/4]==0x1234);
    assert(ccomp_gpio_write(&s,0xd15100c,0x10000000,4));
    assert(!s.ccomp_gpio_request && s.ccomp_gpio_waiting && timer.pending);
    before=s;unsigned old=faults;
    assert(ccomp_gpio_write(&s,0xd15100c,0x10001000,4));
    assert(faults==old+1 && !memcmp(&before,&s,sizeof s));
    now=timer.at;timer.pending=false;ccomp_gpio_feedback(&s);
    assert(!s.ccomp_gpio_waiting && s.ccomp_gpio_level && irq && s.ccomp_gpio_responses==1);
    before=s;ccomp_gpio_feedback(&s);assert(!memcmp(&before,&s,sizeof s));
    old=faults;assert(ccomp_gpio_write(&s,0xd15100c,0x10001000,4));
    assert(faults==old+1 && !memcmp(&before,&s,sizeof s));
    s.gpio_irq_config[0][2]=0;ccomp_gpio_update(&s);assert(!irq);
    assert(ccomp_gpio_write(&s,0xd15100c,0x10001000,4));
    assert(s.ccomp_gpio_requests==2 && !s.ccomp_gpio_level && s.ccomp_gpio_waiting);
    // Masking changes IRQ visibility, never response ownership.
    s.gpio_irq_config[0][0]=0x80;now=timer.at;ccomp_gpio_feedback(&s);
    assert(!irq && s.gpio_irq_config[0][2]==0x80 && s.ccomp_gpio_responses==2);
    s.gpio_irq_config[0][0]=0;ccomp_gpio_update(&s);assert(irq);
    // Existing default: level request falls before feedback and cancels it.
    s.ccomp_gpio_pulse_model=false;s.ccomp_gpio_request=false;s.ccomp_gpio_level=false;
    s.ccomp_gpio_response_delay_ns=0;s.gpio_irq_config[0][2]=0;
    assert(ccomp_gpio_write(&s,0xd15100c,0x10001000,4) && timer.at==now+100000);
    assert(ccomp_gpio_write(&s,0xd15100c,0x10000000,4) && !timer.pending);
    before=s;ccomp_gpio_feedback(&s);assert(!memcmp(&before,&s,sizeof s));
    assert(!ccomp_gpio_write(&s,0xd15100c,0x10001000,8));
    assert(!memcmp(&before,&s,sizeof s));
    puts("PASS GPIO pulse survives request fall, single response, strict overlap, IRQ masks and legacy default");
}
'''
with tempfile.TemporaryDirectory(prefix='z8-ccomp-gpio-') as temp:
    src,exe=Path(temp)/'test.c',Path(temp)/'test'
    src.write_text(prelude+'\n'.join(function(n) for n in ('ccomp_gpio_update','ccomp_gpio_feedback','ccomp_gpio_write'))+main)
    subprocess.run([os.environ.get('CC','cc'),'-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(src),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
