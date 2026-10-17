# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Reject commands outside the observed Z8 F3/1 and opt-in F4/0 contracts."""
from pathlib import Path
import struct
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from ccomp_command_peer import reply_for
from mcu_frames import frames


def request(selector, argument, *, tail=bytes(228), family=9):
    return frames(struct.pack('<3I',2,selector,argument)+tail,family=family)[0]


f3=request(0xf3,1)
f4=request(0xf4,0)
assert reply_for(f3) is not None
assert reply_for(f4) is None
reply=reply_for(f4,allow_f4=True)
assert reply[0]==b'\x03'+bytes(15) and sum(reply[1])&255==255
for selector,argument in ((0xf4,1),(0xf3,0),(0xf5,0),(0,0),(0xf4,2)):
    assert reply_for(request(selector,argument),allow_f4=True) is None
assert reply_for(request(0xf4,0,family=8),allow_f4=True) is None
assert reply_for(request(0xf4,0,tail=b'\x01'+bytes(227)),allow_f4=True) is None
for offset in (0,2,8,12,16,100,255):
    bad=bytearray(f4);bad[offset]^=1
    assert reply_for(bytes(bad),allow_f4=True) is None
assert reply_for(f4[:-1],allow_f4=True) is None
print('PASS request-bound Z8 F4 ACK, default-off, checksum, reserved fields and unknown-command rejection')
