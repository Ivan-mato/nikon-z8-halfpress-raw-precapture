# SPDX-License-Identifier: GPL-3.0-only
"""Run frozen capture driver with a host-transport write allowlist and audit.

No guest instruction, model logic or accepted input value is changed. Rejects
CPU-register writes, arbitrary memory writes and unexpected model injections.
"""
from pathlib import Path
import collections,hashlib,json,runpy,sys,time

source=Path(sys.argv[1]).resolve()
arguments=sys.argv[2:]
out=Path(arguments[arguments.index('--output')+1])
receipt=out.parent/(out.name+'-transport-audit.json')
sys.path.insert(0,str(source/'tools'))
import guest_transport,probe

counts=collections.Counter(); writes=[]; blocked=[]
def reject(kind,value):
    blocked.append(dict(kind=kind,value=value)); raise RuntimeError('Independent transport guard: '+kind+' '+str(value))
qt_original=guest_transport.Transport.qt_command
def qt(self,command):
    kind=command.split()[0]; counts['qtest:'+kind]+=1
    if kind=='writel':
        address=int(command.split()[1],0)
        if address not in (0x0d15100c,0x0d151010):reject('memory write',command)
        writes.append(dict(kind='external_mcu_gpio',command=command))
    elif kind=='set_irq_in':
        writes.append(dict(kind='external_irq',command=command))
    elif kind not in ('read','readl','irq_intercept_in'):
        reject('qtest command',command)
    return qt_original(self,command)
guest_transport.Transport.qt_command=qt

rsp_original=guest_transport.Transport.rsp
def rsp(self,command,**kwargs):
    counts['gdb:'+command.split(',')[0].split(':')[0]]+=1
    if not command.startswith(('Z1,','z1,','Hg','vCont;s:')):reject('GDB mutation/command',command)
    return rsp_original(self,command,**kwargs)
guest_transport.Transport.rsp=rsp

qmp_original=probe.QMP.command
def qmp(self,name,**args):
    counts['qmp:'+name]+=1
    if name=='qom-set':
        prop=args.get('property')
        if args.get('path')!='/machine' or prop not in ('capture-gpio-input','serial-clock','event1508-global1-input','event1508-aux0-input'):
            reject('QOM write',args)
        value=str(args.get('value'))
        writes.append(dict(kind='external_model_input',property=prop,value=value if prop!='serial-clock' else None,
            value_sha256=hashlib.sha256(value.encode()).hexdigest()))
    elif name=='human-monitor-command':
        command=args.get('command-line','')
        if not command.startswith(('info ','pmemsave ')):reject('HMP command',command)
    elif name not in ('qmp_capabilities','qom-get','qom-list','cont','stop','query-status','quit','screendump'):
        reject('QMP command',dict(name=name,args=args))
    return qmp_original(self,name,**args)
probe.QMP.command=qmp

started=time.time()
try:
    sys.argv=[str(source/'tools/capture.py'),*arguments]
    runpy.run_path(str(source/'tools/capture.py'),run_name='__main__')
finally:
    receipt.write_text(json.dumps(dict(tool_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        source=str(source),wall_seconds=time.time()-started,counts=dict(counts),blocked=blocked,
        writes=writes,scope='Host transport write allowlist; no changes to frozen model or guest code'),indent=2)+'\n')
