# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Request-bound CCOMP peer inherited from the Z9 C5.32 functional experiment.

The observed family9/type2 command F3 (argument1) is acknowledged. The
multiframe experiment also admits the exact F4/0 request observed on Z8.
Z8 410202AC constructs both commands (41020334=F4, 41020378=F3);
410203F0 decodes the shared type3 acknowledgement with no result payload.
This models the MCU
command lifecycle, not image processing, exposure hardware or DMA completion.
Other cameras must validate their own decoder before opting in.
"""
import hashlib
import json
import struct

from mcu_frames import frames


def reply_for(wire, *, allow_f4=False):
    """Return an ACK only for the complete, checksummed observed request."""
    if len(wire) != 256 or sum(wire) & 255 != 255:
        return None
    if wire[:4] != bytes((9, 1, 240, 0)) or wire[252:254] != bytes((1, 1)):
        return None
    body = wire[8:248]
    commands = [(0xf3, 1)] + ([(0xf4, 0)] if allow_f4 else [])
    if not any(body == struct.pack('<3I', 2, selector, argument) + bytes(228)
               for selector, argument in commands):
        return None
    body = bytes((3,)) + bytes(15)
    return body, frames(body, family=9)[0]


def queue_reply(peer, wire):
    reply = reply_for(wire, allow_f4=bool(peer.g.data.get('experimental_multiframe')))
    if reply is None:
        return False
    body, frame = reply
    queued_ns = json.loads(peer.g.qmp.command('qom-get', path='/machine',
                                             property='runtime-clock-state'))['virtual_ns']
    peer.record.setdefault('ccomp_command_replies', []).append(dict(
        tx_index=peer.tx['row']['index'], selector=hex(struct.unpack_from('<I', wire, 12)[0]),
        argument=struct.unpack_from('<I', wire, 16)[0],
        queued_virtual_ns=queued_ns,
        request_sha256=hashlib.sha256(wire).hexdigest(),
        reply_body_hex=body.hex(), reply_sha256=hashlib.sha256(frame).hexdigest(),
        classification='functional_mcu_command_ack',
        physical_mcu_verified=False))
    peer.pending.append((9, body, frame))
    return True
