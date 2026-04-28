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
import threading
from net.packet_out import *

allowed_chars = "abcdefghijklmnoprstquvwxyzABCDEFGHIJKLMNOPRSTQUVWXYZ1234567890-_+=!@$%^&*();'\"<>,.?/~`| :"

# Process a recieved ip address.
def parse_ip(a):
    """Decode the 32-bit IP address as sent by the login server (little-endian).

    >>> parse_ip(0)
    '0.0.0.0'
    >>> parse_ip(0x01020304)
    '4.3.2.1'
    >>> parse_ip(0xC0A80101)
    '1.1.168.192'
    """
    return "%s.%s.%s.%s" % ((a % 256),((a >> 8) % 256),((a >> 16) % 256),((a >> 24) % 256))

# Remove colors from a message
def remove_colors(msg):
    """Strip ##X color codes from a chat message.

    >>> remove_colors("hello")
    'hello'
    >>> remove_colors("##5hello")
    'hello'
    >>> remove_colors("a##5b##cc")
    'abc'
    >>> remove_colors("##B##bbold##b")
    'bold'
    """
    if len(msg) > 2:
        for f in range(len(msg)-2):
            while (len(msg) > f + 2) and (msg[f] == "#")\
                and (msg[f+1] == "#"):
                msg = msg[0:f]+msg[f+3:]
    return msg

def normalize_item_name(name):
    """Strip TMW chat-link markup from an item name.

    Supports the right-click "add to chat" formats:

    >>> normalize_item_name("Iron Ore")
    'Iron Ore'
    >>> normalize_item_name("[Concentration Potion]")
    'Concentration Potion'
    >>> normalize_item_name("@@640|Iron Ore@@")
    'Iron Ore'
    >>> normalize_item_name("[@@640|Iron Ore@@]")
    'Iron Ore'
    >>> normalize_item_name("[  Iron Ore  ]")
    'Iron Ore'
    >>> normalize_item_name("@@no-pipe@@")
    '@@no-pipe@@'
    """
    if name.startswith('[') and name.endswith(']'):
        name = name[1:-1].strip()
    if name.startswith('@@') and name.endswith('@@'):
        pipe_index = name.find('|')
        if pipe_index != -1:
            name = name[pipe_index + 1:-2].strip()
    return name


# Encode string - used with 4144 shop compatibility.
def encode_str(value, size):
    """Encode an integer in the 4144 shop wire format (base-94, ASCII 33+).

    Output is `size` characters, padded with '!' (ASCII 33) on the right.

    >>> encode_str(0, 4)
    '!!!!'
    >>> encode_str(1, 1)
    '"'
    >>> encode_str(640, 2)
    "m'"
    >>> encode_str(1000, 2)
    ']+'
    >>> encode_str(94, 2)
    '!"'
    """
    output = ''
    base = 94
    start = 33
    while value:
        output += chr(value % base + start)
        value //= base

    while len(output) < size:
        output += chr(start)

    return output

class ItemDB:
    """
    A simple class to look up information from the items.xml file.
    """
    def __init__(self):
        print("Loading ItemDB")
        self.item_names = {}
        self.itemdb_file = ElementTree(file="data/items.xml")

        for item in self.itemdb_file.getroot():
            ## Item declaration
            if item.get('id'):
                item3 = item
                item_struct = Item()
                item_struct.name = item3.get('name')
                item_struct.weight = int(item3.get('weight', 0))
                if item3.get('type'):
                    item_struct.type = item3.get('type')
                    item_struct.description = item3.get('description')
                    self.item_names[int(item3.get('id'))] = item_struct
            ## Import statement
            elif item.get('name'):
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


def parse_mail_cmdargs(s):
    if len(s) < 3:
        return "", ""
    if s[0] == '"':
        end = s.find('"', 1)
        if end > 0:
            return s[1:end], s[end+2:]
        else:
            return "", ""
    else:
        end = s.find(' ')
        return s[:end], s[end+1:]

class ItemLog:
    """ Writes all sales to a log file, for later processing."""
    def __init__(self):
        self.log_file = 'data/logs/sale.log'

    def add_item(self, item_id, amount, price, name):
        file_node = open(self.log_file, 'a')
        file_node.write(str(item_id)+" "+str(amount)+" "+str(price)+" "+str(time.time())+" "+name+"\n")
        file_node.close()

class TraderState:
    """ Stores information regarding a trade request"""
    def __init__(self):
        self.Trading = threading.Lock()
        self.item = 0
        self.money = 0
        self.complete = 0
        self.timer = 0

    def reset(self):
        if self.Trading.locked():
            self.Trading.release()
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

if __name__ == '__main__':
    import doctest
    failures, tests = doctest.testmod()
    if failures == 0:
        print("All %d doctests passed" % tests)
