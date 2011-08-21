"""
    Copyright 2011, Dipesh Amin <yaypunkrock@gmail.com>

    This package implements an Automated Market Bot for "The Mana World" a 2D MMORPG.

    - Currently permissions are defined as: -1 (blocked), 0 (normal user), 5 (seller), 20 (admin).
    - An item will only be listed for a period of one week, and can be relisted
      for 3 weeks.
    - If a Trade in uncompleted within 5 minutes of a Trade Request, it is cancelled
      to prevent any disruptions to service.
    - The Bot supports the manaplus "right click and buy" feature; if an item is listed
      twice for the same price, the first shown in the list will be bought (i.e. the one added earlier).
"""

import logging
import socket
import sys
import time
import string

from being import *
from config import *
from net.packet import *
from net.protocol import *
from net.packet_out import *
from player import *
import tradey
import utils

shop_broadcaster = utils.Broadcast()
trader_state = utils.TraderState()
ItemDB = utils.ItemDB()
player_node = Player('')
beingManager = BeingManager()
user_tree = tradey.UserTree()
sale_tree = tradey.ItemTree()
ItemLog = utils.ItemLog()

def process_whisper(nick, msg, mapserv):
    msg = filter(lambda x: x in string.printable, msg)
    user = user_tree.get_user(nick)
    broken_string = msg.split()

    if user != -10:
        if int(user.get("accesslevel")) == -1: # A user who has been blocked for abuse.
	    mapserv.sendall(whisper(nick, "You can no longer use the bot. If you feel this is in error, please contact <administrator>."))
	    return

    if msg == "!list":
	# Sends the list of items for sale.
	if len(sale_tree.root) != 0:
	    mapserv.sendall(whisper(nick, "The following items are on sale:"))
	else:
	    mapserv.sendall(whisper(nick, "No items for sale."))

	for elem in sale_tree.root:
	    if time.time() - float(elem.get('add_time')) < 604800: # Check if an items time is up.
		msg = "[selling] [" + elem.get("uid") + "] " + elem.get("amount") + " [@@" + \
		elem.get("itemId") + "|" + ItemDB.getItem(int(elem.get("itemId"))).name + "@@] for " + elem.get("price") + "gp each"
		mapserv.sendall(whisper(nick, msg))

    elif broken_string[0] == '!selllist':
	# Support for 4144's shop (Sell list)
        data = '\302\202B1'

	for elem in sale_tree.root:
	    data += utils.encode_str(int(elem.get("itemId")), 2)
            data += utils.encode_str(int(elem.get("price")), 4)
	    data += utils.encode_str(int(elem.get("amount")), 3)
	mapserv.sendall(whisper(nick, data))

    elif broken_string[0] == '!buyitem':
	# 4144 buy command
	if len(broken_string) == 4:
	    if broken_string[1].isdigit() and broken_string[2].isdigit() and broken_string[3].isdigit():
	        # Traditional 4144 shop.
	        item_id = int(broken_string[1])
	        price = int(broken_string[2])
	        amount = int(broken_string[3])
	        for elem in sale_tree.root:
                    if int(elem.get('amount')) >= amount and int(elem.get('price')) == price and int(elem.get('itemId')) == item_id:
		        process_whisper(nick, '!buy ' + str(amount) + " " + elem.get('uid'), mapserv)
		        return
		mapserv.sendall(whisper(nick, "Item not found. Please check and try again."))
	else:
	    mapserv.sendall(whisper(nick, "Syntax incorrect"))

    elif msg == "!info":
        # Send information related to a player.
	if user == -10:
	    mapserv.sendall(whisper(nick, "Your current access level is 0."))
	elif int(user.get('accesslevel')) > 0:
	    mapserv.sendall(whisper(nick, "Your current access level is " + user.get('accesslevel') + "."))
	    mapserv.sendall(whisper(nick, "Your have the following items for sale:"))
	    for elem in sale_tree.root:
		if elem.get('name') == nick:
	            if time.time() - float(elem.get('add_time')) > 604800:
	                msg = "[expired] ["
	            else:
		        msg = "[selling] ["

		    msg += elem.get("uid") + "] " + elem.get("amount") + " [@@" + elem.get("itemId") + "|" + \
			ItemDB.getItem(int(elem.get("itemId"))).name + "@@] for " + elem.get("price") + "gp each"
	    	    mapserv.sendall(whisper(nick, msg))

	    money = int(user.get('money'))
	    mapserv.sendall(whisper(nick, "You have " + str(money) + "gp to collect."))
	    stall_msg = "You have " + str(int(user.get('stalls')) - int(user.get('used_stalls'))) + " free slots."
	    mapserv.sendall(whisper(nick, stall_msg))

    elif broken_string[0] == "!help":
	# Sends help information
	if len(broken_string) == 1:
            mapserv.sendall(whisper(nick, "Welcome to ManaMarket!"))
	    mapserv.sendall(whisper(nick, "The basic commands for the bot are: !list, !find <id> or <Item Name>, !buy <amount> <uid>, !add <amount> <price> <Item Name>, !money, !relist <uid>, !info, !getback <uid> "))
	    mapserv.sendall(whisper(nick, "For a detailed description of each command, type !help <command> e.g. !help !buy"))
	    mapserv.sendall(whisper(nick, "For example:- to purchase an item shown in the list as:"))
	    mapserv.sendall(whisper(nick, "[selling] [6] 5 [@@640|Iron Ore@@] for 1000gp each"))
	    mapserv.sendall(whisper(nick, "you would type /whisper ManaMarket !buy 1 6" ))
	    mapserv.sendall(whisper(nick, "This will purchase one of item 6 (Iron Ore)."))

	elif len(broken_string) == 2:
	    if broken_string[1] == '!buy':
		mapserv.sendall(whisper(nick, "!buy <amount> <uid> - Request the purchase of an item or items."))
	    elif broken_string[1] == '!list':
		mapserv.sendall(whisper(nick, "!list - Displays a list of all items for sale."))
	    elif broken_string[1] == '!find':
		mapserv.sendall(whisper(nick, "!find <id> or <Item Name> - Simple search to locate an item."))
	    elif broken_string[1] == '!buy':
		mapserv.sendall(whisper(nick, "!buy <amount> <uid> - Request the purchase of an item or items."))
	    elif broken_string[1] == '!add':
		mapserv.sendall(whisper(nick, "!add <amount> <price> <Item Name> - Add an item to the sell list (requires that you have an account)."))
	    elif broken_string[1] == '!money':
		mapserv.sendall(whisper(nick, "!money - Allows you to collect money for any sales made on your behalf."))
	    elif broken_string[1] == '!relist':
	        mapserv.sendall(whisper(nick, "!relist <uid> - Allows you to relist an item which has expired."))
	    elif broken_string[1] == '!info':
		mapserv.sendall(whisper(nick, "!info - Displays basic information about your account."))
	    elif broken_string[1] == '!getback':
		mapserv.sendall(whisper(nick, "!getback <uid> - Allows you to retrieve an item that has expired or you no longer wish to sell."))

    elif msg == "!money":
	# Trades any money earned through item sales.
	if user == -10:
	    mapserv.sendall(whisper(nick, "You don't have the correct permissions."))
	    return

	amount = int(user.get('money'))
	if amount == 0:
	    mapserv.sendall(whisper(nick, "You have no money to collect."))
	else:
	    trader_state.money = nick
	    if not trader_state.Trading.testandset():
		mapserv.sendall(whisper(nick, "I'm currently busy with a trade.  Try again shortly"))
	        return
            player_id = beingManager.findId(nick)

	    if player_id != -10:
	        mapserv.sendall(trade_request(player_id))
                trader_state.timer = time.time()
	    else:
		mapserv.sendall(whisper(nick, "Where are you?!?  I can't trade with somebody who isn't here!"))
		trader_state.reset()

    elif broken_string[0] == "!find":
	# Returns a list of items, with the corresponding Item Id - !find <id> or <item name>.
	if len(broken_string) < 2:
            mapserv.sendall(whisper(nick, "Syntax incorrect."))
	    return

	items_found = False
	item = " ".join(broken_string[1:]) # could be an id or an item name

	if item.isdigit(): # an id
	    for elem in sale_tree.root:
	        if ((time.time() - float(elem.get('add_time'))) < 604800) \
		and int(elem.get("itemId")) == int(item): # Check if an items time is up.
		    msg = "[selling] [" + elem.get("uid") + "] " + elem.get("amount") + " [@@" + elem.get("itemId") + "|" \
                    + ItemDB.getItem(int(elem.get("itemId"))).name + "@@] for " + elem.get("price") + "gp each"
		    mapserv.sendall(whisper(nick, msg))
		    items_found = True
	else: # an item name
	    for elem in sale_tree.root:
	        if ((time.time() - float(elem.get('add_time'))) < 604800) \
		and item.lower() in ItemDB.getItem(int(elem.get("itemId"))).name.lower(): # Check if an items time is up.
		    msg = "[selling] [" + elem.get("uid") + "] " + elem.get("amount") + " [@@" + elem.get("itemId") + "|" \
                    + ItemDB.getItem(int(elem.get("itemId"))).name + "@@] for " + elem.get("price") + "gp each"
		    mapserv.sendall(whisper(nick, msg))
		    items_found = True

	if not items_found:
	    mapserv.sendall(whisper(nick, "Item not found."))

    elif msg == '!listusers':
	# Admin command - shows a list of all user.
        if user == -10:
	    return

        if int(user.get("accesslevel")) != 20:
	    mapserv.sendall(whisper(nick, "You don't have the correct permissions."))
	    return

	data = ''

	for user in user_tree.root:
            name = user.get('name')
            accesslevel = user.get('accesslevel')
	    slots = user.get('stalls')
	    used_slots = user.get('used_stalls')
	    money = user.get('money')
	    data += name+" ("+accesslevel+") "+used_slots+"/"+slots+" "+money+'gp, '
	    # Format ManaMarket (20) 2/5 100000gp,

	    if len(data) > 400:
	        mapserv.sendall(whisper(nick, data[0:len(data)-2]+"."))
		data = ''

        mapserv.sendall(whisper(nick, data[0:len(data)-2]+"."))

    elif broken_string[0] == '!setslots':
	# Change the number of slots a user has - !setslots <slots> <name>
        if user == -10:
	    return

        if int(user.get("accesslevel")) != 20:
	    mapserv.sendall(whisper(nick, "You don't have the correct permissions."))
	    return

	if len(broken_string) < 3:
            mapserv.sendall(whisper(nick, "Syntax incorrect."))
	    return

	if broken_string[1].isdigit():
	    slot = int(broken_string[1])
	    name = " ".join(broken_string[2:])

	    user_info = user_tree.get_user(name)

	    if user_info == -10:
		mapserv.sendall(whisper(nick, "User not found, check and try again."))
	        return

	    user_tree.get_user(name).set('stalls', str(slot))
	    mapserv.sendall(whisper(nick, "Slots changed: "+name+" "+str(slot)))
	    user_tree.save()
	else:
            mapserv.sendall(whisper(nick, "Syntax incorrect."))

    elif broken_string[0] == '!setaccess':
	# Change someones access level - !setaccess <access level> <name>
        if user == -10:
	    return

        if int(user.get("accesslevel")) != 20:
	    mapserv.sendall(whisper(nick, "You don't have the correct permissions."))
	    return

	if len(broken_string) < 3:
            mapserv.sendall(whisper(nick, "Syntax incorrect."))
	    return

	if (broken_string[1][0] == '-' and broken_string[1][1:].isdigit()) or broken_string[1].isdigit():
	    accesslevel = int(broken_string[1])
	    name = " ".join(broken_string[2:])

	    user_info = user_tree.get_user(name)

	    if user_info == -10:
		mapserv.sendall(whisper(nick, "User not found, check and try again."))
		return

	    if int(user_info.get('accesslevel')) < int(user.get("accesslevel")) and accesslevel <= int(user.get("accesslevel")):
		user_tree.get_user(name).set('accesslevel', str(accesslevel))
		mapserv.sendall(whisper(nick, "Access level changed:"+name+ " ("+str(accesslevel)+")."))
		user_tree.save()
	    else:
	        mapserv.sendall(whisper(nick, "You don't have the correct permissions."))
		return
        else:
            mapserv.sendall(whisper(nick, "Syntax incorrect."))


    elif broken_string[0] == "!adduser":
	# A command to give a user access to the bot - !adduser <access level> <stall> <player name>.
        if user == -10:
	    return

        if int(user.get("accesslevel")) != 20:
	    mapserv.sendall(whisper(nick, "You don't have the correct permissions."))
	    return

	if len(broken_string) < 3:
            mapserv.sendall(whisper(nick, "Syntax incorrect."))
	    return

        if broken_string[1].isdigit() and broken_string[2].isdigit():
            al = int(broken_string[1])
            stalls = int(broken_string[2])
            player_name = " ".join(broken_string[3:])
	    user_tree.add_user(player_name, stalls, al)
	    mapserv.sendall(whisper(nick, "User Added with " + str(stalls) + " slots."))
        else:
            mapserv.sendall(whisper(nick, "Syntax incorrect."))

    elif broken_string[0] == "!add":
	# Allows a player with the correct permissions to add an item for sale - !add <amount> <price> <item name>
	if user == -10:
	    mapserv.sendall(whisper(nick, "You are unable to add items."))
	    return

	if len(broken_string) < 3:
            mapserv.sendall(whisper(nick, "Syntax incorrect."))
	    return

	if int(user.get("accesslevel")) < 5:
	    mapserv.sendall(whisper(nick, "You are unable to add items."))
	    return

	if int(user.get("used_stalls")) >= int(user.get("stalls")):
	    mapserv.sendall(whisper(nick, "You have no free slots.  You may remove an item or wait for something to be sold."))
	    return

	if broken_string[1].isdigit() and broken_string[2].isdigit():
	    amount = int(broken_string[1])
	    price = int(broken_string[2])
	    item_name = " ".join(broken_string[3:])
	    item_id = ItemDB.findId(item_name)
	    if item_id == -10:
	        mapserv.sendall(whisper(nick, "Item not found, check spelling."))
		return

	    item = Item()
	    item.player = nick
	    item.get = 1 # 1 = get, 0 = give
	    item.id = item_id
	    item.amount = amount
	    item.price = price
	    trader_state.item = item

	    if not trader_state.Trading.testandset():
		mapserv.sendall(whisper(nick, "I'm currently busy with a trade.  Try again shortly"))
	        return
            player_id = beingManager.findId(nick)
	    if player_id != -10:
	        mapserv.sendall(trade_request(player_id))
                trader_state.timer = time.time()
	    else:
		mapserv.sendall(whisper(nick, "Where are you?!?  I can't trade with somebody who isn't here!"))
		trader_state.reset()
	else:
	    mapserv.sendall(whisper(nick, "Syntax incorrect."))

    elif broken_string[0] == "!buy":
	# Buy a given quantity of an item - !buy <amount> <uid>
	if len(broken_string) != 3:
	    mapserv.sendall(whisper(nick, "Syntax incorrect."))
	    return

	if broken_string[1].isdigit() and broken_string[2].isdigit():
	    amount = int(broken_string[1])
	    uid = int(broken_string[2])
	    item_info = sale_tree.get_uid(uid)

	    if item_info == -10:
		mapserv.sendall(whisper(nick, "Item not found.  Please check the uid number and try again."))
		return

	    if amount > int(item_info.get("amount")):
		mapserv.sendall(whisper(nick, "I do not have that many."))
		return

	    item = Item()
	    item.get = 0 # 1 = get, 0 = give
	    item.player = nick
	    item.id = int(item_info.get("itemId"))
	    item.uid = uid
	    item.amount = amount
	    item.price = int(item_info.get("price"))
	    trader_state.item = item

	    if not trader_state.Trading.testandset():
		mapserv.sendall(whisper(nick, "I'm currently busy with a trade.  Try again shortly"))
	        return
            player_id = beingManager.findId(nick)
	    if player_id != -10:
	        mapserv.sendall(trade_request(player_id))
                trader_state.timer = time.time()
		mapserv.sendall(whisper(nick, "That will be " + str(item.price * item.amount) + "gp."))
	    else:
		mapserv.sendall(whisper(nick, "Where are you?!?  I can't trade with somebody who isn't here!"))
		trader_state.reset()
	else:
	    mapserv.sendall(whisper(nick, "Syntax incorrect."))

    elif broken_string[0] == "!removeuser":
	# Remove a user, for whatever reason - !removeuser <player name>
        if user == -10:
	    return

	if len(broken_string) < 2:
	    mapserv.sendall(whisper(nick, "Syntax incorrect."))
	    return

        if int(user.get("accesslevel")) != 20:
	    mapserv.sendall(whisper(nick, "You don't have the correct permissions."))
	    return

        player_name = " ".join(broken_string[1:])
	check = user_tree.remove_user(player_name)
	if check == 1:
	    mapserv.sendall(whisper(nick, "User Removed."))
	elif check == -10:
	    mapserv.sendall(whisper(nick, "User removal failed. Please check spelling."))

    elif broken_string[0] == "!relist":
        # Relist an item which has expired - !relist <uid>.
	if user == -10 or len(broken_string) != 2:
            mapserv.sendall(whisper(nick, "Syntax incorrect."))
            return

	if int(user.get("accesslevel")) < 5:
	    mapserv.sendall(whisper(nick, "You don't have the correct permissions."))
	    return

	if broken_string[1].isdigit():
	    uid = int(broken_string[1])
	    item_info = sale_tree.get_uid(uid)

	    if item_info == -10:
		mapserv.sendall(whisper(nick, "Item not found.  Please check the uid number and try again."))
		return

	    if item_info.get('name') != nick:
		mapserv.sendall(whisper(nick, "That doesn't belong to you!"))
		return

            time_relisted = int(item_info.get('relisted'))

	    if int(item_info.get('relisted')) < 3:
		sale_tree.get_uid(uid).set('add_time', str(time.time()))
		sale_tree.get_uid(uid).set('relisted', str(time_relisted + 1))
		sale_tree.save()
		mapserv.sendall(whisper(nick, "The item has been successfully relisted."))
	    else:
                mapserv.sendall(whisper(nick, "This item can no longer be relisted. Please collect it using !getback "+str(uid)+"."))
		return
        else:
	    mapserv.sendall(whisper(nick, "Syntax incorrect."))

    elif broken_string[0] == "!getback":
	# Trade the player back uid, remove from sale_items if trade successful - !getback <uid>.
	if user == -10 or len(broken_string) != 2:
            mapserv.sendall(whisper(nick, "Syntax incorrect."))
	    return

	if int(user.get("accesslevel")) < 5:
	    mapserv.sendall(whisper(nick, "You don't have the correct permissions."))
	    return

	if broken_string[1].isdigit():
	    uid = int(broken_string[1])
	    item_info = sale_tree.get_uid(uid)

	    if item_info == -10:
		mapserv.sendall(whisper(nick, "Item not found.  Please check the uid number and try again."))
		return

	    if item_info.get('name') != nick:
		mapserv.sendall(whisper(nick, "That doesn't belong to you!"))
		return

	    item = Item()
	    item.get = 0
	    item.player = nick
	    item.id = int(item_info.get("itemId"))
	    item.uid = uid
	    item.amount = int(item_info.get("amount"))
	    item.price = 0
	    trader_state.item = item

	    if not trader_state.Trading.testandset():
		mapserv.sendall(whisper(nick, "I'm currently busy with a trade.  Try again shortly"))
	        return
            player_id = beingManager.findId(nick)
	    if player_id != -10:
	        mapserv.sendall(trade_request(player_id))
                trader_state.timer = time.time()
	    else:
		mapserv.sendall(whisper(nick, "Where are you?!?  I can't trade with somebody who isn't here!"))
		trader_state.reset()

def main():
    logging.basicConfig(filename='data/logs/activity.log', level=logging.INFO, format='%(asctime)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    logging.info("Bot Started.")

    account = sys.argv[1]
    password = sys.argv[2]
    character = sys.argv[3]

    login = socket.socket()
    login.connect((server, port))
    print("Login connected")

    login_packet = PacketOut(0x0064)
    login_packet.write_int32(0)
    login_packet.write_string(account, 24)
    login_packet.write_string(password, 24)
    login_packet.write_int8(0x03);
    login.sendall(str(login_packet))

    pb = PacketBuffer()
    id1 = accid = id2 = 0
    charip = ""
    charport = 0
    # Login server packet loop.
    while True:
	#time.sleep(0.1)
        data = login.recv(1500)
        if not data:
            break
        pb.feed(data)
        for packet in pb:
            if packet.is_type(SMSG_LOGIN_DATA): # login succeeded
		packet.skip(2)
		id1 = packet.read_int32()
		accid = packet.read_int32()
		id2 = packet.read_int32()
		packet.skip(30)
		player_node.sex = packet.read_int8()
                charip = utils.parse_ip(packet.read_int32())
                charport = packet.read_int16()
                login.close()
                break
        if charip:
            break

    assert charport

    char = socket.socket()
    char.connect((charip, charport))
    print("Char connected")
    char_serv_packet = PacketOut(CMSG_CHAR_SERVER_CONNECT)
    char_serv_packet.write_int32(accid)
    char_serv_packet.write_int32(id1)
    char_serv_packet.write_int32(id2)
    char_serv_packet.write_int16(0)
    char_serv_packet.write_int8(player_node.sex)
    char.sendall(str(char_serv_packet))
    char.recv(4)

    pb = PacketBuffer()
    mapip = ""
    mapport = 0
    # Character Server Packet loop.
    while True:
        data = char.recv(1500)
        if not data:
            break
        pb.feed(data)
        for packet in pb:
            if packet.is_type(SMSG_CHAR_LOGIN):
		packet.skip(2)
		slots = packet.read_int16()
		packet.skip(18)
		count = (len(packet.data)-22) / 106
		for i in range(count):
		    player_node.id = packet.read_int32()
		    player_node.EXP = packet.read_int32()
		    player_node.MONEY = packet.read_int32()
		    packet.skip(30)
		    player_node.HP = packet.read_int16()
		    player_node.MAX_HP = packet.read_int16()
		    player_node.MP = packet.read_int16()
		    player_node.MAX_MP = packet.read_int16()
		    packet.skip(8)
		    player_node.LEVEL = packet.read_int16()
		    packet.skip(14)
		    player_node.name = packet.read_string(24)
		    packet.skip(6)
                    slot = packet.read_int8()
		    packet.skip(1)
		    print "Character information recieved:"
		    print "Name: %s, Id: %s, EXP: %s, MONEY: %s, HP: %s/%s, MP: %s/%s, LEVEL: %s"\
                        % (player_node.name, player_node.id, player_node.EXP, player_node.MONEY, player_node.HP, player_node.MAX_HP, player_node.MP, player_node.MAX_MP, player_node.LEVEL)
		    if slot == int(character):
			break

		char_select_packet = PacketOut(CMSG_CHAR_SELECT)
		char_select_packet.write_int8(int(character))
		char.sendall(str(char_select_packet))

            elif packet.is_type(SMSG_CHAR_MAP_INFO):
		player_node.id = packet.read_int32()
		player_node.map = packet.read_string(16)
                mapip = utils.parse_ip(packet.read_int32())
                mapport = packet.read_int16()
                char.close()
                break
        if mapip:
            break

    assert mapport

    beingManager.container[player_node.id] = Being(player_node.id, 42)
    mapserv = socket.socket()
    mapserv.connect((mapip, mapport))
    print("Map connected")
    mapserv_login_packet = PacketOut(CMSG_MAP_SERVER_CONNECT)
    mapserv_login_packet.write_int32(accid)
    mapserv_login_packet.write_int32(player_node.id)
    mapserv_login_packet.write_int32(id1)
    mapserv_login_packet.write_int32(id2)
    mapserv_login_packet.write_int8(player_node.sex)
    mapserv.sendall(str(mapserv_login_packet))
    mapserv.recv(4)

    pb = PacketBuffer()
    shop_broadcaster.mapserv = mapserv
    # Map server packet loop

    while True:
        data = mapserv.recv(2048)
        if not data:
            break
        pb.feed(data)

        # For unfinished trades - one way to distrupt service would be leaving a trade active.
        if trader_state.Trading.test():
            if time.time() - trader_state.timer > 5*60:
                logging.info("Trade Cancelled - Timeout.")
                trader_state.timer = time.time()
                mapserv.sendall(str(PacketOut(CMSG_TRADE_CANCEL_REQUEST)))

        for packet in pb:
            if packet.is_type(SMSG_MAP_LOGIN_SUCCESS): # connected
		logging.info("Map login success.")
		packet.skip(4)
		coord_data = packet.read_coord_dir()
		player_node.x = coord_data[0]
		player_node.y = coord_data[1]
		player_node.direction = coord_data[2]
		print "Starting Postion: %s %s %s" % (player_node.map, player_node.x, player_node.y)
                mapserv.sendall(str(PacketOut(CMSG_MAP_LOADED))) # map loaded
		# A Thread to send a shop broadcast: also keeps the network active to prevent timeouts.
		shop_broadcaster.start()

            elif packet.is_type(SMSG_WHISPER):
		msg_len = packet.read_int16() - 26
                nick = packet.read_string(24)
                message = packet.read_raw_string(msg_len)
		logging.info("Whisper: " + nick + ": " + message)
		if nick != "guild":
		    process_whisper(nick, utils.remove_colors(message), mapserv)

            elif packet.is_type(SMSG_PLAYER_CHAT): # server speech
		msg_len = packet.read_int16() - 2
		being_id = packet.read_int32()
                message = packet.read_string(msg_len)
                if "automaticly banned for spam" in message:
                    time.sleep(3)

            elif packet.is_type(SMSG_BEING_CHAT): # char speech
		msg_len = packet.read_int16() - 2
		being_id = packet.read_int32()
                message = packet.read_string(msg_len)

            elif packet.is_type(SMSG_WALK_RESPONSE):
		packet.read_int32()
		coord_data = packet.read_coord_pair()
		player_node.x = coord_data[2]
		player_node.y = coord_data[3]

            elif packet.is_type(SMSG_PLAYER_STAT_UPDATE_1):
		stat_type = packet.read_int16()
		value = packet.read_int32()
		if stat_type == 0x0005:
		    player_node.HP = value
		elif stat_type == 0x0006:
		    player_node.MaxHP = value
		elif stat_type == 0x0007:
		    player_node.MP = value
		elif stat_type == 0x0008:
		    player_node.MaxMP = value
		elif stat_type == 0x000b:
		    player_node.LEVEL = value
		    print "Level changed: %s" % value
		elif stat_type == 0x0018:
		    print "Weight changed from %s/%s to %s/%s" % (player_node.WEIGHT, player_node.MaxWEIGHT, value, player_node.MaxWEIGHT)
		    logging.info("Weight changed from %s/%s to %s/%s", player_node.WEIGHT, player_node.MaxWEIGHT, value, player_node.MaxWEIGHT)
		    player_node.WEIGHT = value
		elif stat_type == 0x0019:
		    print "Max Weight: %s" % value
		    player_node.MaxWEIGHT = value

            elif packet.is_type(SMSG_PLAYER_STAT_UPDATE_2):
		stat_type = packet.read_int16()
		value = packet.read_int32()
		if stat_type == 0x0001:
		    player_node.EXP = value
		elif stat_type == 0x0014:
		    logging.info("Money Changed from %s, to %s", player_node.MONEY, value)
		    print "Money Changed from %s, to %s" % (player_node.MONEY, value)
		    player_node.MONEY = value
		elif stat_type == 0x0016:
		    player_node.EXP_NEEDED = value
		    print "Exp Needed: %s" % player_node.EXP_NEEDED

            elif packet.is_type(SMSG_BEING_MOVE) or packet.is_type(SMSG_BEING_VISIBLE)\
            or packet.is_type(SMSG_PLAYER_MOVE) or packet.is_type(SMSG_PLAYER_UPDATE_1)\
            or packet.is_type(SMSG_PLAYER_UPDATE_2):
		being_id = packet.read_int32()
                packet.skip(8)
		job = packet.read_int16()
		if being_id not in beingManager.container:
	            if job == 0 and id >= 110000000 and (packet.is_type(SMSG_BEING_MOVE)\
                                                         or packet.is_type(SMSG_BEING_VISIBLE)):
		        continue
		    # Add the being to the BeingManager, and request name.
		    beingManager.container[being_id] = Being(being_id, job)
		    requestName = PacketOut(0x0094)
		    requestName.write_int32(being_id)
		    mapserv.sendall(str(requestName))

		packet.skip(8)

		if (packet.is_type(SMSG_BEING_MOVE) or packet.is_type(SMSG_PLAYER_MOVE)):
		    packet.read_int32()

		packet.skip(22)

		if (packet.is_type(SMSG_BEING_MOVE) or packet.is_type(SMSG_PLAYER_MOVE)):
		    coord_data = packet.read_coord_pair()
		    beingManager.container[being_id].dst_x = coord_data[2]
		    beingManager.container[being_id].dst_y = coord_data[3]
		else:
		    coord_data = packet.read_coord_dir()
		    beingManager.container[being_id].x = coord_data[0]
                    beingManager.container[being_id].y = coord_data[1]
		    beingManager.container[being_id].direction = coord_data[2]

	    elif packet.is_type(SMSG_BEING_NAME_RESPONSE):
	        being_id = packet.read_int32()
		if being_id in beingManager.container:
		    beingManager.container[being_id].name = packet.read_string(24)

	    elif packet.is_type(SMSG_BEING_REMOVE):
	        being_id = packet.read_int32()
		if being_id in beingManager.container:
		    del beingManager.container[being_id]

	    elif packet.is_type(SMSG_PLAYER_WARP):
		player_node.map = packet.read_string(16)
	        player_node.x = packet.read_int16()
		player_node.y = packet.read_int16()
		logging.info("Player warped.")
                mapserv.sendall(str(PacketOut(CMSG_MAP_LOADED)))

	    elif packet.is_type(SMSG_BEING_ACTION):
		src_being = packet.read_int32()
		dst_being = packet.read_int32()
		packet.skip(12)
		param1 = packet.read_int16()
		packet.skip(2)
		action_type = packet.read_int8()

		if src_being in beingManager.container:
		    if action_type == 0: # Damage
		        beingManager.container[src_being].action = "attack"
		        beingManager.container[src_being].target = dst_being

		    elif action_type == 0x02: # Sit
		        beingManager.container[src_being].action = "sit"

		    elif action_type == 0x03: # Stand up
		        beingManager.container[src_being].action = "stand"

            elif packet.is_type(SMSG_PLAYER_INVENTORY_ADD):
		item = Item()
                item.index = packet.read_int16() - inventory_offset
		item.amount = packet.read_int16()
		item.itemId = packet.read_int16()
		item.identified = packet.read_int8()
		packet.read_int8()
		item.refine = packet.read_int8()
		packet.skip(8)
		item.equipType = packet.read_int16()
		item.itemType = packet.read_int8()
		err = packet.read_int8()

                if err == 0:
		    if item.index in player_node.inventory:
		        player_node.inventory[item.index].amount += item.amount
		    else:
		        player_node.inventory[item.index] = item

		    print "Picked up: %s, Amount: %s" % (ItemDB.getItem(item.itemId).name, item.amount)
	            logging.info("Picked up: %s, Amount: %s", ItemDB.getItem(item.itemId).name, str(item.amount))

            elif packet.is_type(SMSG_PLAYER_INVENTORY_REMOVE):
		index = packet.read_int16() - inventory_offset
                amount = packet.read_int16()

		print "Remove item: %s, Amount: %s" % (ItemDB.getItem(player_node.inventory[index].itemId).name, amount)
		logging.info("Remove item: %s, Amount: %s", ItemDB.getItem(player_node.inventory[index].itemId).name, str(amount))
		if index in player_node.inventory:
		    player_node.inventory[index].amount -= amount
		    if player_node.inventory[index].amount == 0:
		        del player_node.inventory[index]

            elif packet.is_type(SMSG_PLAYER_INVENTORY):
		player_node.inventory.clear() # Clear the inventory - incase of new index.
		packet.skip(2)
		number = (len(packet.data)-2) / 18
                for loop in range(number):
		    item = Item()
		    item.index = packet.read_int16() - inventory_offset
		    item.itemId = packet.read_int16()
		    item.itemType = packet.read_int8()
		    item.identified = packet.read_int8()
		    item.amount = packet.read_int16()
		    item.arrow = packet.read_int16()
		    packet.skip(8) # Cards
		    player_node.inventory[item.index] = item

            elif packet.is_type(SMSG_PLAYER_EQUIPMENT):
		packet.read_int16()
		number = (len(packet.data)) / 20
                for loop in range(number):
		    item = Item()
		    item.index = packet.read_int16() - inventory_offset
		    item.itemId = packet.read_int16()
		    item.itemType = packet.read_int8()
		    item.identified = packet.read_int8()
		    packet.skip(2)
		    item.equipType = packet.read_int16()
		    packet.skip(1)
		    item.refine = packet.read_int8()
		    packet.skip(8)
		    item.amount = 1
		    player_node.inventory[item.index] = item

		for item in player_node.inventory:
		    print "Name: %s, Id: %s, Index: %s, Amount: %s." % \
                    (ItemDB.getItem(player_node.inventory[item].itemId).name, \
                     player_node.inventory[item].itemId, item, player_node.inventory[item].amount)

	    elif packet.is_type(SMSG_TRADE_REQUEST):
		print "SMSG_TRADE_REQUEST"
		name = packet.read_string(24)
		logging.info("Trade request: " + name)

	    elif packet.is_type(SMSG_TRADE_RESPONSE):
		print "SMSG_TRADE_RESPONSE"
		response = packet.read_int8()
		time.sleep(0.2)
		if response == 0:
		    logging.info("Trade response: Too far away.")
		    if trader_state.item:
		        mapserv.sendall(whisper(trader_state.item.player, "You are too far away."))
		    elif trader_state.money:
			mapserv.sendall(whisper(trader_state.money, "You are too far away."))
		    trader_state.reset()

		elif response == 3:
		    logging.info("Trade response: Trade accepted.")
		    if trader_state.item:
		        if trader_state.item.get == 1: # add
		            mapserv.sendall(str(PacketOut(CMSG_TRADE_ADD_COMPLETE)))
		        elif trader_state.item.get == 0: # buy
			    if player_node.find_inventory_index(trader_state.item.id) != -10:
			        mapserv.sendall(trade_add_item(player_node.find_inventory_index(trader_state.item.id), trader_state.item.amount))
			        mapserv.sendall(str(PacketOut(CMSG_TRADE_ADD_COMPLETE)))
			        if trader_state.item.price == 0: # getback
			            mapserv.sendall(str(PacketOut(CMSG_TRADE_OK)))
			            trader_state.complete = 1

		    elif trader_state.money: # money
			amount = int(user_tree.get_user(trader_state.money).get('money'))
			mapserv.sendall(trade_add_item(0-inventory_offset, amount))
			mapserv.sendall(str(PacketOut(CMSG_TRADE_ADD_COMPLETE)))
			mapserv.sendall(str(PacketOut(CMSG_TRADE_OK)))
			trader_state.complete = 1

		elif response == 4:
		    logging.info("Trade response: Trade cancelled")
		    trader_state.reset()

	    elif packet.is_type(SMSG_TRADE_ITEM_ADD):
		print "SMSG_TRADE_ITEM_ADD"
		amount = packet.read_int32()
		item_id = packet.read_int16()
		if trader_state.item and trader_state.money == 0:
		    if  trader_state.item.get == 1: # add
		        if amount == trader_state.item.amount and item_id == trader_state.item.id:
			    trader_state.complete = 1
		            mapserv.sendall(str(PacketOut(CMSG_TRADE_OK)))
		        else:
			    mapserv.sendall(whisper(trader_state.item.player, "Thats not the right item."))
			    mapserv.sendall(str(PacketOut(CMSG_TRADE_CANCEL_REQUEST)))

		    elif trader_state.item.get == 0: # buy
		        if amount == trader_state.item.price * trader_state.item.amount and item_id == 0:
		            mapserv.sendall(str(PacketOut(CMSG_TRADE_OK)))
			    trader_state.complete = 1
			elif item_id == 0 and amount != trader_state.item.price * trader_state.item.amount:
			    trader_state.complete = 0
		        else:
			    if item_id == 0:
			        mapserv.sendall(whisper(trader_state.item.player, "Please verify you have the correct amount of money and try again."))
			    else:
				mapserv.sendall(whisper(trader_state.item.player, "Don't give me your itenz."))
			    mapserv.sendall(str(PacketOut(CMSG_TRADE_CANCEL_REQUEST)))

		elif trader_state.money: # money
		    mapserv.sendall(whisper(trader_state.money, "Don't give me your itenz."))
		    mapserv.sendall(str(PacketOut(CMSG_TRADE_CANCEL_REQUEST)))

		logging.info("Trade item add: ItemId:%s Amount:%s", item_id, amount)
		# Note item_id = 0 is money

	    elif packet.is_type(SMSG_TRADE_ITEM_ADD_RESPONSE):
		print "SMSG_TRADE_ITEM_ADD_RESPONSE"
		index = packet.read_int16() - inventory_offset
		amount = packet.read_int16()
		response = packet.read_int8()

		if response == 0:
		    logging.info("Trade item add response: Successfully added item.")
		    if trader_state.item:
			if trader_state.item.get == 0 and index != 0-inventory_offset: # Make sure the correct item is given!
                            if player_node.inventory[index].itemId != trader_state.item.id and \
                                amount != trader_state.item.amount:
                                mapserv.sendall(str(PacketOut(CMSG_TRADE_CANCEL_REQUEST)))

		    # If Trade item add successful - Remove the item from the inventory state.
		    if index != 0-inventory_offset: # If it's not money
		        print "Remove item: %s, Amount: %s" % (ItemDB.getItem(player_node.inventory[index].itemId).name, amount)
		        logging.info("Remove item: %s, Amount: %s", ItemDB.getItem(player_node.inventory[index].itemId).name, str(amount))
		        if index in player_node.inventory:
		            player_node.inventory[index].amount -= amount
		            if player_node.inventory[index].amount == 0:
		                del player_node.inventory[index]

		elif response == 1:
		    logging.info("Trade item add response: Failed - player overweight.")
		    mapserv.sendall(str(PacketOut(CMSG_TRADE_CANCEL_REQUEST)))
		    if trader_state.item:
		        mapserv.sendall(whisper(trader_state.item.player, "You are carrying too much weight. Unload and try again."))
		elif response == 2:
		    if trader_state.item:
		        mapserv.sendall(whisper(trader_state.item.player, "You have no free slots."))
		    logging.info("Trade item add response: Failed - No free slots.")
		    mapserv.sendall(str(PacketOut(CMSG_TRADE_CANCEL_REQUEST)))

	    elif packet.is_type(SMSG_TRADE_OK):
		print "SMSG_TRADE_OK"
		is_ok = packet.read_int8() # 0 is ok from self, and 1 is ok from other
		if is_ok == 0:
		    logging.info("Trade OK: Self.")
		else:
		    if trader_state.complete:
		        mapserv.sendall(str(PacketOut(CMSG_TRADE_OK)))
		    else:
			mapserv.sendall(str(PacketOut(CMSG_TRADE_CANCEL_REQUEST)))
			mapserv.sendall(whisper(trader_state.item.player, "Trade Cancelled: Please check the traded items or money."))

		    logging.info("Trade Ok: Partner.")

	    elif packet.is_type(SMSG_TRADE_CANCEL):
		trader_state.reset()
		logging.info("Trade Cancel.")
		print "SMSG_TRADE_CANCEL"

	    elif packet.is_type(SMSG_TRADE_COMPLETE):
		# The sale_tree is only ammended after a complete trade packet.
		if trader_state.item and trader_state.money == 0:
		    if trader_state.item.get == 1: # !add
		        sale_tree.add_item(trader_state.item.player, trader_state.item.id, trader_state.item.amount, trader_state.item.price)
		        user_tree.get_user(trader_state.item.player).set('used_stalls', \
                                                                         str(int(user_tree.get_user(trader_state.item.player).get('used_stalls')) + 1))

		    elif trader_state.item.get == 0: # !buy \ !getback
		        seller = sale_tree.get_uid(trader_state.item.uid).get('name')
		        item = sale_tree.get_uid(trader_state.item.uid)
		        current_amount = int(item.get("amount"))
		        sale_tree.get_uid(trader_state.item.uid).set("amount", str(current_amount - trader_state.item.amount))
		        if int(item.get("amount")) == 0:
			    user_tree.get_user(sale_tree.get_uid(trader_state.item.uid).get('name')).set('used_stalls', \
                                                                                                         str(int(user_tree.get_user(sale_tree.get_uid(trader_state.item.uid).get('name')).get('used_stalls'))-1))
			    sale_tree.remove_item_uid(trader_state.item.uid)

		        current_money = int(user_tree.get_user(seller).get("money"))
		        user_tree.get_user(seller).set("money", str(current_money + trader_state.item.price * trader_state.item.amount))

			if trader_state.item.price * trader_state.item.amount != 0:
			    ItemLog.add_item(int(item.get('itemId')), trader_state.item.amount, trader_state.item.price * trader_state.item.amount)

		elif trader_state.money and trader_state.item == 0: # !money
		    user_tree.get_user(trader_state.money).set('money', str(0))

		sale_tree.save()
		user_tree.save()
		trader_state.reset()
		logging.info("Trade Complete.")
		print "SMSG_TRADE_COMPLETE"
            else:
		pass
	        #print "Unhandled Packet: %s" % hex(packet.get_type())

    # On Disconnect/Exit
    shop_broadcaster.stop()
    mapserv.close()

if __name__ == '__main__':
    main()
