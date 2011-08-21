class Item:
    pass

class Player:
    def __init__(self, name):
        self.inventory = {}
        self.storage = []
        self.name = name
        self.id = 0
        self.sex = 0
        self.map = ""
        self.x = 0
        self.y = 0

        self.EXP_NEEDED = 0
        self.EXP = 0
        self.MONEY = 0
        self.LEVEL = 0
        self.HP = 0
        self.MaxHP = 0
        self.MP = 0
        self.MaxMP = 0
        self.WEIGHT = 0
        self.MaxWEIGHT = 0

    def find_inventory_index(self, item_id):
        for item in self.inventory:
            if item > 1:
                if self.inventory[item].itemId == item_id:
                    return item
        return -10 # Not found - bug somewhere!
