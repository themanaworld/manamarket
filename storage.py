#!/usr/bin/python

"""
    Copyright 2011, Dipesh Amin <yaypunkrock@gmail.com>
    Copyright 2011, Stefan Beller <stefanbeller@googlemail.com>

    This file is part of tradey, a trading bot in the mana world
    see www.themanaworld.org

    Storage Access class by Fernanda Monteiro <crie.fernanda@gmail.com>
"""

from utils import ItemDB
from net.packet_out import chat
from net.protocol import *
from net.packet import *
import time
import copy
import mutex

class Storage:
	def __init__(self):
		self.storage = {}
		self.timer = 0
		self.Open = mutex.mutex()
	def reset(self):
		self.Open.unlock()
		self.timer = 0

	def find_storage_index(self, item_id):
		for item in self.storage:
			if item > 1:
				if self.storage[item].itemId == item_id:
					return item
		return -10 # Not found - bug somewhere!

	def add_item(self, item):
		if not item.itemId or item.amount <= 0:
			return -10 # Not an item - something is messy

		index = self.find_storage_index(item.itemId)
		if ItemDB().getItem(item.itemId).type != 'equip-ammo' and 'equip':
			if index != -10:
				if (item.amount > MAX_AMOUNT - self.storage[index].amount):
					return -10
				self.storage[index].amount += item.amount
				return 0

		index = len(self.storage)
		self.storage[index] = item
		self.storage[index].amount = item.amount
		return index

	def remove_item(self, index, amount):
		if index in self.storage:
			self.storage[index].amount -= amount
			if self.storage[index].amount == 0:
				del self.storage[index]

	def check_storage(self, stack_tree, delisted_tree):
		# Check the inventory state.
		test_node = copy.deepcopy(self.storage)
		for elem in stack_tree.root:
			item_found = False
			for item in test_node:
				if int(elem.get('itemId')) == test_node[item].itemId \
				and int(elem.get('amount')) <= test_node[item].amount:
					test_node[item].amount -= int(elem.get('amount'))
					if test_node[item].amount == 0:
						del test_node[item]
					item_found = True
					break

			if not item_found:
				return "Server and client storage out of sync."

		for elem in delisted_tree.root:
			item_found = False
			for item in test_node:
				if int(elem.get('itemId')) == test_node[item].itemId \
				and int(elem.get('amount')) <= test_node[item].amount:
					test_node[item].amount -= int(elem.get('amount'))
					if test_node[item].amount == 0:
						del test_node[item]
					item_found = True
					break

			if not item_found:
				return "Server and client storage out of sync."

	def storage_send(self, mapserv, index, amount):
		packet = PacketOut(CMSG_MOVE_TO_STORAGE)
		packet.write_int16(index + inventory_offset)
		packet.write_int32(amount)
		mapserv.sendall(str(packet))
		return 0

	def storage_get(self, mapserv, index, amount):
		packet = PacketOut(CMSG_MOVE_FROM_STORAGE)
		packet.write_int16(index + storage_offset)
		packet.write_int32(amount)
		mapserv.sendall(str(packet))
		return 0

	def storage_open(self, mapserv):
		mapserv.sendall(chat("@storage"))
		self.timer = time.time()

	def storage_close(self, mapserv):
		mapserv.sendall(str(PacketOut(CMSG_CLOSE_STORAGE)))

if __name__ == '__main__':
    print "Do not run this file directly. Run main.py"

