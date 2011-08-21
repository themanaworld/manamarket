#!/usr/bin/python
"""
    Copyright 2011, Dipesh Amin <yaypunkrock@gmail.com>
    Copyright 2011, Stefan Beller <stefanbeller@googlemail.com>

    This file is part of tradey, a trading bot in the mana world
    see www.themanaworld.org
"""
import time
import os
from subprocess import call
from xml.etree.ElementTree import *

class UserTree:
    def __init__(self):
        self.tree = ElementTree(file="data/user.xml")
        self.root = self.tree.getroot()

    def add_user(self, name, stalls, al):
        if self.get_user(name) == -10:
            user = SubElement(self.root, "user")
            user.set("name", name)
            user.set("stalls", str(stalls))
            user.set("used_stalls", str(0))
            user.set("money", str(0))
            user.set("id", str(0))
            user.set("accesslevel", str(al))
            self.save()

    def get_user(self, name):
        for elem in self.root:
            if elem.get("name") == name:
                return elem
        return -10

    def remove_user(self, name):
        for elem in self.root:
            if elem.get("name") == name:
                self.root.remove(elem)
                self.save()
                return 1
        return -10

    def save(self):
        # Be sure to call save() after any changes to the tree.
        self.tree = ElementTree(self.root)
        self.tree.write("data/user.xml")

class ItemTree:
    def __init__(self):
        self.tree = ElementTree(file="data/sale.xml")
        self.root = self.tree.getroot()
        self.u_id = set()

        for elem in self.root:
            self.u_id.add(int(elem.get("uid")))

    def getId(self):
        id_itter = 1
        while id_itter in self.u_id:
                id_itter += 1
        self.u_id.add(id_itter)
        return id_itter

    def remove_id(self, uid):
        # Free up used id's.
        self.u_id.remove(uid)

    def add_item(self, name, item_id, amount, price):
        user = SubElement(self.root, "item")
        user.set("name", name)
        user.set("itemId", str(item_id))
        user.set("price", str(price))
        user.set("add_time", str(time.time()))
        user.set("relisted", str(0))
        user.set("amount", str(amount))
        user.set("uid", str(self.getId()))
        self.save()

    def get_uid(self, uid):
        for elem in self.root:
            if elem.get("uid") == str(uid):
                return elem
        return -10

    def remove_item_uid(self, uid):
        for elem in self.root:
            if elem.get("uid") == str(uid):
                self.root.remove(elem)
                self.remove_id(uid)
                self.save()
                return 1
        return -10

    def save(self):
        # Be sure to call save() after any changes to the tree.
        self.tree = ElementTree(self.root)
        self.tree.write("data/sale.xml")

def saveData(commitmessage = "commit"):
    cwd = os.getcwd()
    os.chdir("data")
    call(["git", "commit","-a", '-m "' + commitmessage + '"'])
    os.chdir("..")


if __name__ == '__main__':
    print "Do not run this file directly. Run main.py"
