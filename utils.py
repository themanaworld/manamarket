#!/usr/bin/python
"""
    Copyright 2011, Dipesh Amin <yaypunkrock@gmail.com>
    Copyright 2011, Stefan Beller <stefanbeller@googlemail.com>

    This file is part of tradey, a trading bot in the mana world
    see www.themanaworld.org
"""
from xml.etree.ElementTree import ElementTree
from player import Item

import time
import mutex
import threading
from net.packet_out import *
from threading import _Timer

allowed_chars = "abcdefghijklmnoprstquvwxyzABCDEFGHIJKLMNOPRSTQUVWXYZ1234567890-_+=!@$%^&*();'<>,.?/~`| "

# Process a recieved ip address.
def parse_ip(a):
    return "%s.%s.%s.%s" % ((a % 256),((a >> 8) % 256),((a >> 16) % 256),((a >> 24) % 256))

# Remove colors from a message
def remove_colors(msg):
    if len(msg) > 2:
        for f in range(len(msg)-2):
            while (len(msg) > f + 2) and (msg[f] == "#")\
                and (msg[f+1] == "#"):
                msg = msg[0:f]+msg[f+3:]
    return msg

# Encode string - used with 4144 shop compatibility.
def encode_str(value, size):
    output = ''
    base = 94
    start = 33
    while value:
        output += chr(value % base + start)
        value /= base

    while len(output) < size:
        output += chr(start)

    return output

class ItemDB:
    """
    A simple class to look up information from the items.xml file.
    """
    def __init__(self):
        print "Loading ItemDB"
        self.item_names = {}
        self.itemdb_file = ElementTree(file="data/items.xml")

        for item in self.itemdb_file.getroot():
            if item.get('name'):
                file2 = ElementTree(file=item.get('name'))
                for item2 in file2.getroot():
                    if item2.get('name'):
                        file3 = ElementTree(file=item2.get('name'))
                        for item3 in file3.getroot():
                            item_struct = Item()
                            item_struct.name = item3.get('name')
                            item_struct.weight = int(item3.get('weight', 0))
                            if item3.get('type'):
                                item_struct.type = item3.get('type')
                                item_struct.description = item3.get('description')
                                self.item_names[int(item3.get('id'))] = item_struct

    def getItem(self, item_id):
        return self.item_names[item_id]

    def findId(self, name):
        for item_id in self.item_names:
            if self.item_names[item_id].name == name:
                return item_id
        return -10 #Not found

class ItemLog:
    """ Writes all sales to a log file, for later processing."""
    def __init__(self):
        self.log_file = 'data/logs/sale.log'

    def add_item(self, item_id, amount, price, name):
        file_node = open(self.log_file, 'a')
        file_node.write(str(item_id)+" "+str(amount)+" "+str(price)+" "+str(time.time())+" "+name+"\n")
        file_node.close()

class DelistedLog:
    def __init__(self):
        self.log_file = 'data/logs/delisted.log'

    def add_item(self, item_id, amount, name):
        file_node = open(self.log_file, 'a')
        file_node.write(str(item_id)+" "+str(amount)+" "+str(time.time())+" "+name+"\n")
        file_node.close()

class TraderState:
    """ Stores information regarding a trade request"""
    def __init__(self):
        self.Trading = mutex.mutex()
        self.item = 0
        self.money = 0
        self.complete = 0
        self.timer = 0

    def reset(self):
        self.Trading.unlock()
        self.item = 0
        self.complete = 0
        self.money = 0
        self.timer = 0

class Broadcast:
    """Send a message to the server every 5 minutes to avoid a timeout."""

    def __init__(self):
        self.mapserv = 0
        self.Active = False
        self.Timer = 0
        self.shop_broadcast = threading.Thread(target=self.send_broadcast, args=())

    def send_broadcast(self):
        while self.Active:
            if (time.time() - self.Timer) > 60:
                self.mapserv.sendall(emote(193))
                self.Timer = time.time()
                #print "shop_broadcast"
            else:
                time.sleep(0.1)

    def start(self):
        self.Active = True
        self.shop_broadcast.start()

    def stop(self):
        if self.Active:
            self.Active = False
            self.shop_broadcast.join()

class CustomTimer(_Timer):
    def __init__(self, interval, function, args=[], kwargs={}):
        self._original_function = function
        super(CustomTimer, self).__init__(interval, self._do_execute, args, kwargs)
        self._result = None

    def _do_execute(self, *a, **kw):
        self._result = self._original_function(*a, **kw)

    def join(self):
        super(CustomTimer, self).join()
        return self._result

if __name__ == '__main__':
    print "Do not run this file directly. Run main.py"
