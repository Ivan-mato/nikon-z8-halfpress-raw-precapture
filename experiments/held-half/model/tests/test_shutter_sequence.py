# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Regress held FULL and native relative mode inputs without firmware."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from shutter_sequence import held_sequence, release_mode_steps


class ShutterTests(unittest.TestCase):
    def test_one_hold_has_one_full_edge_and_requested_duration(self):
        for duration in (0.1, 2, 20, 300):
            sequence = held_sequence(duration)
            now, inputs = 0, []
            for contact in sequence:
                now += contact.wait_before
                inputs.append((now, contact.half, contact.full))
            self.assertEqual(sum(full for _, _, full in inputs), 1)
            self.assertAlmostEqual(inputs[3][0] - inputs[2][0], duration)
            self.assertEqual(inputs[-1][1:], (0, 0))
            self.assertTrue(all(not full or half for _, half, full in inputs))

    def test_nonfinite_or_unbounded_hold_is_rejected(self):
        for duration in (float('nan'), float('inf'), -1, 0, 301):
            with self.assertRaises(ValueError):
                held_sequence(duration)

    def test_mode_deltas_have_neutral_records_and_no_shutter(self):
        for steps in (-7, -1, 1, 7):
            records = release_mode_steps(steps)
            bodies = [bytes.fromhex(row['body_hex']) for row in records]
            self.assertTrue(all(len(b) == 124 and b[0] == b[4] == 1 for b in bodies))
            self.assertTrue(all(b[7] == b[8] == 0 for b in bodies))
            self.assertTrue(all(all(not v for i,v in enumerate(b)
                                   if i not in (0,4,0x10,0x0b)) for b in bodies))
            deltas = [int.from_bytes(b[0x0b:0x0c], signed=True) for b in bodies]
            self.assertEqual(sum(deltas), steps)
            self.assertFalse(any(a and b for a,b in zip(deltas,deltas[1:])))
            self.assertTrue(all(b[0x10] for b in bodies[:-1]))
            self.assertEqual(bodies[-1][0x10], 0)

    def test_zero_steps_preserves_existing_recipe(self):
        self.assertEqual(release_mode_steps(0), [])
        for steps in (-8, 8, 1.5):
            with self.assertRaises(ValueError):
                release_mode_steps(steps)


if __name__ == '__main__':
    unittest.main()
