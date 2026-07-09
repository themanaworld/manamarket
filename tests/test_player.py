"""Tests for Player.held_amount.

The !add trade flow lists the quantity that actually arrived (held_amount after
the trade minus held_amount before it) rather than the quantity offered. The
server refuses adds it can't fully honour (a stack passing 30000, overweight,
no free slot) while still completing the trade, so the two can differ; listing
the offered amount is what produces the "inventory mismatch" that disables
trading. held_amount must therefore sum a single item id across every slot it
may be spread over.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from player import Item, Player


def make_item(item_id, amount):
    item = Item()
    item.itemId = item_id
    item.amount = amount
    return item


class HeldAmountTests(unittest.TestCase):
    def test_absent_item_is_zero(self):
        player = Player('bot')
        self.assertEqual(player.held_amount(1199), 0)

    def test_single_slot(self):
        player = Player('bot')
        player.inventory = {2: make_item(1199, 20000)}
        self.assertEqual(player.held_amount(1199), 20000)

    def test_sums_across_slots(self):
        player = Player('bot')
        player.inventory = {
            2: make_item(1199, 20000),
            5: make_item(1199, 9000),
            7: make_item(535, 3),
        }
        self.assertEqual(player.held_amount(1199), 29000)

    def test_ignores_other_items(self):
        player = Player('bot')
        player.inventory = {2: make_item(535, 3), 3: make_item(560, 1)}
        self.assertEqual(player.held_amount(1199), 0)

    def test_delta_is_amount_actually_received(self):
        # A stack-full add: bot holds 20000, player offers 25000, server keeps
        # the bot at the 30000 cap by delivering only 10000. The listed amount
        # must be the 10000 delta, not the 25000 offered.
        player = Player('bot')
        player.inventory = {2: make_item(1199, 20000)}
        held_before = player.held_amount(1199)
        player.inventory[2].amount = 30000  # server delivered 10000 of the 25000
        received = player.held_amount(1199) - held_before
        self.assertEqual(received, 10000)


if __name__ == '__main__':
    unittest.main()
