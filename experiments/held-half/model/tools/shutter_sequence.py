# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""One held shutter gesture, paced on the guest virtual clock."""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class Contact:
    half: int
    full: int
    wait_before: float


def held_sequence(hold_seconds=2.0):
    if not math.isfinite(hold_seconds) or not 0.1 <= hold_seconds <= 300:
        raise ValueError('Hold duration must be 0.1..300 virtual seconds')
    return (
        Contact(0, 0, 2.0),
        Contact(1, 0, 2.0),
        Contact(1, 1, 2.0),
        Contact(1, 0, hold_seconds),
        Contact(0, 0, 2.0),
    )


def release_mode_steps(steps):
    """Relative native mode-button/main-dial input; does not assert a UI mode.

    C3.11 decoder: body[0x10] -> SW1 bit27; signed body[0x0b] ->
    status word4. Every dial delta is separated by a neutral record.
    """
    if not isinstance(steps, int) or not -7 <= steps <= 7:
        raise ValueError('Release mode steps must be an integer in -7..7')
    if not steps:
        return []

    def record(label, held, delta):
        body = bytearray(124)
        body[0] = body[4] = 1
        body[0x10] = int(held)
        body[0x0b] = delta & 0xff
        return dict(label=label, body_hex=body.hex())

    result = [record('release-mode-hold', True, 0)]
    for i in range(abs(steps)):
        result.append(record(f'release-mode-step-{i+1}', True, 1 if steps > 0 else -1))
        result.append(record(f'release-mode-neutral-{i+1}', True, 0))
    result.append(record('release-mode-release', False, 0))
    return result
