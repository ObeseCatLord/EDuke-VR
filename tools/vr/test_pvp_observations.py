#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""CPU-only checks for PvP observation false positives/negatives; no game launch."""
import unittest
from smoke_pvp import held_fire_suppressed, scores_stable

class Observations(unittest.TestCase):
    def test_scores_reject_a_regression_after_convergence(self):
        good={'frag':1,'deaths':0,'self':0}
        self.assertTrue(scores_stable([good,dict(good)],True))
        self.assertFalse(scores_stable([good,dict(good,frag=0)],True))
        self.assertFalse(scores_stable([dict(good,self=1)],True))
        self.assertTrue(scores_stable([{'frag':0,'deaths':1,'self':0}],False))
        self.assertFalse(scores_stable([{'frag':0,'deaths':0,'self':0}],False))
        self.assertFalse(scores_stable([],True))

    def test_held_fire_allows_pickups_but_rejects_consumption_input_or_shots(self):
        rows=[{'ammo':48,'bits':0},{'ammo':96,'bits':0}]
        self.assertTrue(held_fire_suppressed(rows,[]))
        self.assertFalse(held_fire_suppressed(rows+[{'ammo':95,'bits':0}],[]))
        self.assertFalse(held_fire_suppressed([{'ammo':48,'bits':4}],[]))
        self.assertFalse(held_fire_suppressed(rows,[{'sprite':3}]))
        self.assertFalse(held_fire_suppressed([],[]))

if __name__=='__main__':unittest.main()
