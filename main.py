#!/usr/bin/env python3
"""
Copyright 2011, Dipesh Amin <yaypunkrock@gmail.com>
Copyright 2011, Stefan Beller <stefanbeller@googlemail.com>

This file is part of tradey, a trading bot in The Mana World
see www.themanaworld.org

This program is free software; you can redistribute it and/or modify it
under the terms of the GNU General Public License as published by the Free
Software Foundation; either version 2 of the License, or (at your option)
any later version.

This program is distributed in the hope that it will be useful, but WITHOUT
ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for
more details.

You should have received a copy of the GNU General Public License along with
this program. If not, see <http://www.gnu.org/licenses/>.

Additionally to the GPL, you are *strongly* encouraged to share any modifications
you do on these sources.
"""

import logging
import logging.handlers
import socket
import sys
import time
import string
from collections import namedtuple
from dataclasses import dataclass

try:
    import config
except:
    print("no config file found. please move config.py.template to config.py and edit to your needs!")
    sys.exit(0)

from being import *
from net.packet import *
from net.protocol import *
from net.packet_out import *
from player import *
import tradey
import utils
import eliza
from onlineusers import SqliteDbManager
from ircbot import IRCBot
from sdnotify import SystemdNotifier

# Flush logs per line so they reach the systemd journal promptly;
# stdout is block-buffered otherwise (not a TTY under systemd), which
# hides connect/disconnect diagnostics until the buffer happens to fill.
sys.stdout.reconfigure(line_buffering=True)

chatbot = eliza.eliza()
shop_broadcaster = utils.Broadcast()
trader_state = utils.TraderState()
ItemDB = utils.ItemDB()
player_node = Player('')
beingManager = BeingManager()
user_tree = tradey.UserTree()
sale_tree = tradey.ItemTree()
ItemLog = utils.ItemLog()
logger = logging.getLogger('ManaLogger')
db_manager = SqliteDbManager(config.sqlite3_dbfile)
ircbot = IRCBot()
sd = SystemdNotifier()

# How long to wait between WATCHDOG=1 systemd keepalives, in seconds
sd_min_keepalive_rate = 5

# Toggled off when check_inventory() detects the bot's in-game state
# disagrees with what data/{user,sale}.xml say it should be. The bot
# stays online (and the IRC bridge keeps working) so an admin can
# investigate, but commands that would initiate a trade get a polite
# refusal instead of corrupting bookkeeping further.
trading_enabled = True

# Whisper commands that initiate or complete a trade. Anything else
# (info, help, list, find, listusers, accesslevel admin, ...) keeps
# working even while trading is disabled.
TRADE_COMMANDS = {"!money", "!add", "!buy", "!buyitem", "!relist", "!getback"}


# --- Command dispatch -------------------------------------------------
#
# Commands are small handlers registered in COMMANDS by the @command
# decorator. The dispatcher (process_whisper, at the end) sanitises the
# message, applies the shared gates (blocked user, trading frozen,
# minimum access level), then calls the handler with a Ctx. Handlers
# talk back through ctx.reply() and raise Reply(...) to bail out with a
# message, which keeps each one focused on its own logic.

class Reply(Exception):
    """Raised by a handler to send one message and stop processing."""
    def __init__(self, message):
        self.message = message


@dataclass
class Ctx:
    nick: str
    user: object        # user XML element, or None when unregistered
    args: list          # message words after the command
    mapserv: object
    msg: str            # the full sanitised whisper

    def reply(self, message):
        self.mapserv.sendall(whisper(self.nick, message))

    @property
    def access(self):
        return int(self.user.get("accesslevel")) if self.user is not None else 0


Command = namedtuple("Command", ["fn", "access", "registered"])
COMMANDS = {}


def command(*names, access=0, registered=False):
    """Register a handler under one or more command words. `access` is the
    minimum level the dispatcher enforces before the handler runs;
    `registered` requires the user to exist in the user tree."""
    def register(fn):
        for name in names:
            COMMANDS[name] = Command(fn, access, registered)
        return fn
    return register


def listing_active(elem):
    return time.time() - float(elem.get('add_time')) < config.relist_time


def format_listing(elem, tag="selling"):
    name = ItemDB.getItem(int(elem.get("itemId"))).name
    return (f"[{tag}] [{elem.get('uid')}] {elem.get('amount')} "
            f"[@@{elem.get('itemId')}|{name}@@] for {elem.get('price')}gp each")


def find_sale(uid):
    item = sale_tree.get_uid(uid)
    return None if item == -10 else item


def find_user(name):
    user = user_tree.get_user(name)
    return None if user == -10 else user


def hold_trade_lock(ctx):
    if not trader_state.Trading.acquire(False):
        raise Reply("I'm currently busy with a trade.  Try again shortly")


def begin_trade(ctx, quote=None):
    """Send a trade request to the requesting player, or apologise. The
    caller must have populated trader_state and acquired the lock."""
    player_id = beingManager.findId(ctx.nick)
    if player_id == -10:
        ctx.reply("Where are you?!?  I can't trade with somebody who isn't here!")
        trader_state.reset()
        return
    ctx.mapserv.sendall(trade_request(player_id))
    trader_state.timer = time.time()
    if quote is not None:
        ctx.reply(quote)


@command("!list")
def cmd_list(ctx):
    ctx.reply("The following items are on sale:" if len(sale_tree.root) != 0
              else "No items for sale.")
    for elem in sale_tree.root:
        if listing_active(elem):
            ctx.reply(format_listing(elem))


@command("!selllist")
def cmd_selllist(ctx):
    # Support for 4144's shop (Sell list).
    data = '\302\202B1'
    for elem in sale_tree.root:
        if listing_active(elem):
            data += utils.encode_str(int(elem.get("itemId")), 2)
            data += utils.encode_str(int(elem.get("price")), 4)
            data += utils.encode_str(int(elem.get("amount")), 3)
    ctx.reply(data.encode('latin-1'))


@command("!buyitem")
def cmd_buyitem(ctx):
    # 4144 buy command (traditional 4144 shop).
    match ctx.args:
        case [item_id, price, amount] if item_id.isdigit() and price.isdigit() and amount.isdigit():
            item_id, price, amount = int(item_id), int(price), int(amount)
            for elem in sale_tree.root:
                if (int(elem.get('amount')) >= amount and int(elem.get('price')) == price
                        and int(elem.get('itemId')) == item_id):
                    process_whisper(ctx.nick, f"!buy {amount} {elem.get('uid')}", ctx.mapserv)
                    return
            ctx.reply("Item not found. Please check and try again.")
        case [_, _, _]:
            pass  # four-token form but not all numeric: a 4144 quirk, stay silent
        case _:
            ctx.reply("Syntax incorrect")


@command("!info")
def cmd_info(ctx):
    # Send information related to a player.
    if ctx.user is None:
        ctx.reply("Your current access level is 0. Request access in [@@https://forums.themanaworld.org/viewtopic.php?f=14&t=14010|ManaMarket's forum thread@@]")
        return
    if ctx.access <= 0:
        return  # registered but level 0: nothing to show
    ctx.reply(f"Your current access level is {ctx.user.get('accesslevel')}.")
    mine = [elem for elem in sale_tree.root if elem.get('name') == ctx.nick]
    if mine:
        ctx.reply("Your have the following items for sale:")
        for elem in mine:
            ctx.reply(format_listing(elem, "selling" if listing_active(elem) else "expired"))
    else:
        ctx.reply("You have no items for sale.")
    ctx.reply(f"You have {int(ctx.user.get('money'))}gp to collect.")
    free = int(ctx.user.get('stalls')) - int(ctx.user.get('used_stalls'))
    ctx.reply(f"You have {free} free slots.")


@command("!money", registered=True)
def cmd_money(ctx):
    # Trades any money earned through item sales.
    money = int(ctx.user.get('money'))
    if money == 0:
        ctx.reply("You have no money to collect.")
        return
    hold_trade_lock(ctx)
    trader_state.money = ctx.nick
    begin_trade(ctx)


@command("!help")
def cmd_help(ctx):
    match ctx.args:
        case []:
            ctx.reply("Welcome to ManaMarket!")
            ctx.reply("The basic commands for the bot are: !list, !find <id> or <Item Name>, !buy <amount> <uid>, !add <amount> <price> <Item Name>, !money, !relist <uid>, !info, !getback <uid>, !irc <on|off>, !mail <nick> <message>, !lastseen <nick> ")
            ctx.reply("For a detailed description of each command, type !help <command> e.g. !help !buy")
            ctx.reply("For example to purchase an item shown in the list as:")
            ctx.reply("[selling] [6] 5 [@@640|Iron Ore@@] for 1000gp each")
            ctx.reply("you would type /whisper ManaMarket !buy 1 6")
            ctx.reply("This will purchase one of item 6 (Iron Ore).")
            if ctx.user is not None:
                if ctx.access >= 5:
                    ctx.reply("---")
                    ctx.reply("Ah, you have sellers access level. How lovely!")
                    ctx.reply("Use !add to tell me which items I should trade for you:")
                    ctx.reply("For example !add 10 1000 Iron Ore would tell me to sell 10 [@@640|Iron Ore@@] for a price of 1000 gp")
                    ctx.reply("Later you can whisper me !money to get back your money. In the example given, I'd give you 10*1000 = 10000gp")
                    ctx.reply("When you just want to know, which items you have given me or how much money I have for you can whisper me !info")
                    ctx.reply("If you want to get back an unsold item, whisper me !getback <uid>")
                if ctx.access >= 10:
                    ctx.reply("---")
                    ctx.reply("You have moderator access. You can also use: !listusers, !adduser <access level> <slots> <name>")
                if ctx.access == 20:
                    ctx.reply("You're my master! How should I serve you?")
                    ctx.reply("As an admin you can also use: !setslots <slots> <name>, !setaccess <access level> <name>, !removeuser <name>")
        case [topic]:
            # Accept both "!help !buy" and "!help buy".
            cmd = topic if topic.startswith('!') else '!' + topic
            texts = {
                '!buy': "!buy <amount> <uid> - Request the purchase of an item or items.",
                '!list': "!list - Displays a list of all items for sale.",
                '!find': "!find <id> or <Item Name> - Simple search to locate an item.",
                '!add': "!add <amount> <price> <Item Name> - Add an item to the sell list (requires that you have an account).",
                '!money': "!money - Allows you to collect money for any sales made on your behalf.",
                '!relist': "!relist <uid> - Allows you to relist an item which has expired.",
                '!info': "!info - Displays basic information about your account.",
                '!getback': "!getback <uid> - Allows you to retrieve an item that has expired or you no longer wish to sell.",
                '!lastseen': "!lastseen <nick> - Show when <nick> was online the last time.",
                '!mail': "!mail <nick> <message> - Send a message to <nick>.",
                '!irc': "!irc <on|off> - Enable/disable IRC mode (the channel is also bridged to Discord).",
            }
            gated = {
                '!listusers': (10, "!listusers - Lists all users which have a special accesslevel, e.g. they are blocked, seller or admin"),
                '!adduser': (10, "!adduser <access level> <slots> <name> - Add a user to the bot, a seller should be added with access level 5."),
                '!setslots': (20, "!setslots <slots> <name> - Sets the number of slots available to a given user."),
                '!setaccess': (20, "!setaccess <access level> <name> - Sets access level for the player: -1 is blocked, 5 is seller and 20 is admin"),
                '!removeuser': (20, "!removeuser <name> - Removes a user from the bot, freeing their slots."),
            }
            help_text = texts.get(cmd)
            if help_text is None and cmd in gated:
                need, text = gated[cmd]
                if ctx.access >= need:
                    help_text = text
            if help_text is not None:
                ctx.reply(help_text)
            else:
                ctx.reply("No help available for '" + cmd + "'. Type !help for a list of commands.")
        case _:
            pass  # !help with extra arguments: stay silent


@command("!find")
def cmd_find(ctx):
    # Locate an item by id or by (partial) name - !find <id> or <item name>.
    if not ctx.args:
        raise Reply("Syntax incorrect.")
    term = " ".join(ctx.args)
    by_id = term.isdigit()
    found = False
    for elem in sale_tree.root:
        if not listing_active(elem):
            continue
        name = ItemDB.getItem(int(elem.get("itemId"))).name
        if (by_id and int(elem.get("itemId")) == int(term)) or \
           (not by_id and term.lower() in name.lower()):
            ctx.reply(format_listing(elem))
            found = True
    if not found:
        ctx.reply("Item not found.")


@command("!tradestate", access=20)
def cmd_tradestate(ctx):
    ctx.reply("I'm busy with a trade." if trader_state.Trading.locked() else "I'm free.")


@command("!identify", access=10)
def cmd_identify(ctx):
    if len(ctx.args) != 1:
        raise Reply("Syntax incorrect.")
    (uid,) = ctx.args
    if not uid.isdigit():
        return  # a non-numeric uid is silently ignored
    item = find_sale(int(uid))
    if item is None:
        raise Reply("Item not found. Please check the uid number and try again.")
    weight = ItemDB.item_names[int(item.get('itemId'))].weight * int(item.get("amount"))
    ctx.reply("That item/s belongs to: " + item.get("name"))
    ctx.reply(f"The weight used is: {weight}/{player_node.MaxWEIGHT}")


@command("!listusers", access=10)
def cmd_listusers(ctx):
    data = ''
    total_money = total_reserved = total_used = count = 0
    for u in user_tree.root:
        count += 1
        slots, used, money = u.get('stalls'), u.get('used_stalls'), u.get('money')
        total_reserved += int(slots)
        total_used += int(used)
        total_money += int(money)
        data += f"{u.get('name')} ({u.get('accesslevel')}) {used}/{slots} {money}gp, "
        if len(data) > 400:
            ctx.reply(data[:-2] + ".")
            data = ''
    if data:
        ctx.reply(data[:-2] + ".")
    ctx.reply(f"Number of users:{count}, Sale slots used: {total_used}/{total_reserved}, "
              f"Total Money: {total_money}, Char slots used: {len(player_node.inventory)}, "
              f"Weight Used: {player_node.WEIGHT}/{player_node.MaxWEIGHT}")


@command("!setslots", access=20)
def cmd_setslots(ctx):
    # Change the number of slots a user has - !setslots <slots> <name>.
    if len(ctx.args) < 2:
        raise Reply("Syntax incorrect.")
    slots, *name_parts = ctx.args
    if not slots.isdigit():
        raise Reply("Syntax incorrect.")
    slots = int(slots)
    name = " ".join(name_parts)
    target = find_user(name)
    if target is None:
        raise Reply("User not found, check and try again.")
    target.set('stalls', str(slots))
    ctx.reply(f"Slots changed: {name} {slots}")
    tradey.saveData(f"User: {name}, Slots changed: {slots}")
    user_tree.save()


@command("!setaccess", access=20)
def cmd_setaccess(ctx):
    # Change someone's access level - !setaccess <access level> <name>.
    if len(ctx.args) < 2:
        raise Reply("Syntax incorrect.")
    level, *name_parts = ctx.args
    if not ((level[0] == '-' and level[1:].isdigit()) or level.isdigit()):
        raise Reply("Syntax incorrect.")
    new_level = int(level)
    name = " ".join(name_parts)
    target = find_user(name)
    if target is None:
        raise Reply("User not found, check and try again.")
    if int(target.get('accesslevel')) < ctx.access and new_level <= ctx.access:
        target.set('accesslevel', str(new_level))
        ctx.reply(f"Access level changed:{name} ({new_level}).")
        user_tree.save()
        tradey.saveData(f"User: {name}, Set Access Level: {new_level}")
    else:
        raise Reply("You don't have the correct permissions.")


@command("!adduser", access=10)
def cmd_adduser(ctx):
    # Give a user access to the bot - !adduser <access level> <slots> <name>.
    if len(ctx.args) < 2:
        raise Reply("Syntax incorrect.")
    al, slots, *name_parts = ctx.args
    if not (al.isdigit() and slots.isdigit()):
        raise Reply("Syntax incorrect.")
    if int(al) > ctx.access:
        raise Reply("You can't give someone a higher accesslevel than your own.")
    al, slots = int(al), int(slots)
    player_name = " ".join(name_parts)
    target = find_user(player_name)
    if target is None:
        user_tree.add_user(player_name, slots, al)
    else:
        target.set("accesslevel", str(al))
        target.set("stalls", str(slots))
    ctx.reply(f"User Added with {slots} slots.")
    tradey.saveData(f"User Added: {player_name}, Slots: {slots}, Access Level: {al}")


@command("!add")
def cmd_add(ctx):
    # Add an item for sale - !add <amount> <price> <item name>.
    if ctx.user is None:
        raise Reply("You are unable to add items. Request access in [@@https://forums.themanaworld.org/viewtopic.php?f=14&t=14010|ManaMarket's forum thread@@]")
    if len(ctx.args) < 2:
        raise Reply("Syntax incorrect.")
    if ctx.access < 5:
        raise Reply("You are unable to add items.")
    if int(ctx.user.get("used_stalls")) >= int(ctx.user.get("stalls")):
        raise Reply("You have no free slots.  You may remove an item or wait for something to be sold.")
    amount, price, *name_parts = ctx.args
    if not (amount.isdigit() and price.isdigit()):
        raise Reply("Syntax incorrect.")
    amount, price = int(amount), int(price)
    item_name = utils.normalize_item_name(" ".join(name_parts))
    item_id = ItemDB.findId(item_name)
    if item_id == -10:
        raise Reply("Item not found, check spelling.")
    weight = ItemDB.item_names[item_id].weight * amount
    if item_id in config.nosell:
        raise Reply("That item can't be added to ManaMarket, as its too heavy.")
    if int(weight) + player_node.WEIGHT > player_node.MaxWEIGHT:
        raise Reply("I've not got enough room left to carry those. Please try again later. ")
    if amount > 1 and ItemDB.getItem(item_id).type != 'equip-ammo' and 'equip' in ItemDB.getItem(item_id).type:
        raise Reply("You can only add one piece of equipment per slot.")
    if price == 0 or price > 50000000:
        raise Reply("Please use a valid price between 1-50000000gp.")
    if amount == 0:
        raise Reply("You can't add 0 of an item.")
    order = Item()
    order.player = ctx.nick
    order.get = 1  # 1 = get, 0 = give
    order.id = item_id
    order.amount = amount
    order.price = price
    hold_trade_lock(ctx)
    trader_state.item = order
    begin_trade(ctx)


@command("!buy")
def cmd_buy(ctx):
    # Buy a given quantity of an item - !buy <amount> <uid>.
    match ctx.args:
        case [amount, uid_str] if amount.isdigit() and uid_str.isdigit():
            amount, uid = int(amount), int(uid_str)
            item = find_sale(uid)
            if item is None:
                raise Reply("Item not found.  Please check the uid number and try again.")
            if amount > int(item.get("amount")):
                raise Reply("I do not have that many.")
            if item.get("name") == ctx.nick:
                raise Reply("You can not buy your own items. To get back the item whisper me !getback " + uid_str)
            order = Item()
            order.get = 0  # 1 = get, 0 = give
            order.player = ctx.nick
            order.id = int(item.get("itemId"))
            order.uid = uid
            order.amount = amount
            order.price = int(item.get("price"))
            hold_trade_lock(ctx)
            trader_state.item = order
            begin_trade(ctx, quote=f"That will be {order.price * order.amount}gp.")
        case _:
            raise Reply("Syntax incorrect.")


@command("!removeuser", access=20)
def cmd_removeuser(ctx):
    # Remove a user, freeing their slots - !removeuser <player name>.
    if not ctx.args:
        raise Reply("Syntax incorrect.")
    player_name = " ".join(ctx.args)
    if user_tree.remove_user(player_name) == 1:
        ctx.reply("User Removed.")
        tradey.saveData(f"User Removed: {player_name}")
    else:
        ctx.reply("User removal failed. Please check spelling.")


@command("!relist", access=5)
def cmd_relist(ctx):
    # Relist an item which has expired - !relist <uid>.
    if len(ctx.args) != 1:
        raise Reply("Syntax incorrect.")
    (uid_str,) = ctx.args
    if not uid_str.isdigit():
        raise Reply("Syntax incorrect.")
    uid = int(uid_str)
    item = find_sale(uid)
    if item is None:
        raise Reply("Item not found.  Please check the uid number and try again.")
    if item.get('name') != ctx.nick:
        raise Reply("That doesn't belong to you!")
    relisted = int(item.get('relisted'))
    if relisted >= 3:
        raise Reply(f"This item can no longer be relisted. Please collect it using !getback {uid}.")
    item.set('add_time', str(time.time()))
    item.set('relisted', str(relisted + 1))
    sale_tree.save()
    ctx.reply("The item has been successfully relisted.")
    user_tree.get_user(ctx.nick).set('last_use', str(time.time()))
    user_tree.save()


@command("!getback")
def cmd_getback(ctx):
    # Trade an unsold item back to its owner - !getback <uid>. There is no
    # access-level gate: the ownership check below (item belongs to nick)
    # is the real guard, so anyone registered can reclaim their own items,
    # including a demoted seller who still has stock listed.
    if ctx.user is None or len(ctx.args) != 1:
        raise Reply("Syntax incorrect.")
    (uid_str,) = ctx.args
    if not uid_str.isdigit():
        return  # a non-numeric uid is silently ignored
    uid = int(uid_str)
    item = find_sale(uid)
    if item is None:
        raise Reply("Item not found.  Please check the uid number and try again.")
    if item.get('name') != ctx.nick:
        raise Reply("That doesn't belong to you!")
    order = Item()
    order.get = 0
    order.player = ctx.nick
    order.id = int(item.get("itemId"))
    order.uid = uid
    order.amount = int(item.get("amount"))
    order.price = 0
    hold_trade_lock(ctx)
    trader_state.item = order
    begin_trade(ctx)


@command("!lastseen")
def cmd_lastseen(ctx):
    who = ctx.msg[10:].strip()
    if not who:
        ctx.reply("Usage: !lastseen <nick>")
    else:
        ctx.reply(db_manager.get_lastseen_info(who))


@command("!mail")
def cmd_mail(ctx):
    if ctx.user is None:
        raise Reply("Your current access level is 0. Request access in [@@https://forums.themanaworld.org/viewtopic.php?f=14&t=14010|ManaMarket's forum thread@@]")
    to_, body = utils.parse_mail_cmdargs(ctx.msg[6:].strip())
    if to_ == "" or body == "":
        raise Reply('Usage: !mail <nick> <message> OR !mail "nick with spaces" <message>')
    db_manager.send_mail(ctx.nick, to_, body)
    ctx.reply(f'Message to "{to_}" sent')


@command("!irc")
def cmd_irc(ctx):
    match ctx.args:
        case ["on", *_]:
            if ctx.user is None:
                user_tree.add_user(ctx.nick, 0, 0)
            target = user_tree.get_user(ctx.nick)
            target.set("irc", "on")
            user_tree.save()
            tradey.saveData(f"IRC relay enabled for {ctx.nick}")
            ctx.reply("IRC relay mode is now enabled (the channel is also bridged to Discord).")
        case ["off", *_]:
            if ctx.user is not None:
                if (int(ctx.user.get("accesslevel")) == 0 and int(ctx.user.get("stalls")) == 0
                        and int(ctx.user.get("money")) == 0):
                    user_tree.remove_user(ctx.nick)
                    tradey.saveData(f"Stub User Removed: {ctx.nick}")
                else:
                    ctx.user.set("irc", "off")
                    user_tree.save()
                    tradey.saveData(f"IRC relay disabled for {ctx.nick}")
            ctx.reply("IRC relay mode is now disabled.")
        case []:
            ctx.reply("Incorrect syntax.")
        case _:
            pass  # unknown !irc subcommand: stay silent, as before


def relay_or_hint(ctx, name):
    """Not a known command: relay to IRC for opted-in users, hint at a
    mistyped command, or hand the message to the chatbot."""
    if ctx.user is not None and ctx.user.get("irc") == "on":
        if not ircbot.isAFK(ctx.msg):  # don't relay AFK messages
            ircbot.send(ctx.nick, ctx.msg)
            db_manager.forEachOnline(broadcast_if_irc_on, ctx.nick, f"TMW.{ctx.nick}: {ctx.msg}")
    elif name.startswith('!'):
        ctx.reply("Command not recognised, please whisper me !help for a full list of commands.")
    else:
        response = chatbot.respond(ctx.msg)
        logger.info("Bot Response: " + response)
        ctx.reply(response)


def process_whisper(nick, msg, mapserv):
    msg = ''.join(c for c in msg if c in utils.allowed_chars)
    if len(msg) == 0:
        return

    # Infinite chat loop anyone?
    if nick == "guild":
        return

    parts = msg.split()
    if len(parts) == 0:
        return
    name, *args = parts

    raw_user = user_tree.get_user(nick)
    user = None if raw_user == -10 else raw_user
    ctx = Ctx(nick=nick, user=user, args=args, mapserv=mapserv, msg=msg)

    if user is not None and ctx.access == -1:  # a user blocked for abuse
        if int(user.get("used_stalls")) == 0 and int(user.get("money")) == 0:
            ctx.reply("You can no longer use the bot. If you feel this is in error, please contact" + config.admin)
            return
        allowed_commands = ['!money', '!help', '!getback', '!info']
        if name not in allowed_commands:
            ctx.reply("Your access level has been set to blocked! If you feel this is in error, please contact" + config.admin)
            ctx.reply("Though, you still can do the following: " + str(allowed_commands))
            return

    if not trading_enabled and name in TRADE_COMMANDS:
        ctx.reply("Trading is currently unavailable due to an inventory mismatch. Please contact " + config.admin + ".")
        return

    cmd = COMMANDS.get(name)
    if cmd is None:
        relay_or_hint(ctx, name)
        return
    if cmd.registered and ctx.user is None:
        ctx.reply("You don't have the correct permissions.")
        return
    if cmd.access > 0 and ctx.access < cmd.access:
        ctx.reply("You don't have the correct permissions.")
        return

    try:
        cmd.fn(ctx)
    except Reply as r:
        ctx.reply(r.message)

def broadcast_from_irc(nick, msg):
    db_manager.forEachOnline(broadcast_if_irc_on, "IRC", f"IRC.{nick}: {msg}")

def broadcast_if_irc_on(pl, sender_nick, msg):
    if sender_nick == pl:
        return
    pl_user = user_tree.get_user(pl)
    if pl_user != -10 and pl_user.get("irc") == "on":
        mapserv.sendall(whisper(pl, msg))

def main():
    # Use rotating log files.
    log_handler = logging.handlers.RotatingFileHandler('data/logs/activity.log', maxBytes=1048576*3, backupCount=5)
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    log_handler.setFormatter(formatter)
    logger.addHandler(log_handler)

    logger.info("Bot Started.")

    account = config.account
    password = config.password
    character = config.character

    login = socket.socket()
    login.connect((config.server, config.port))
    logger.info("Login connected")

    login_packet = PacketOut(0x0064)
    login_packet.write_int32(9) # <= CLIENT VERSION
    login_packet.write_string(account, 24)
    login_packet.write_string(password, 24)
    login_packet.write_int8(0x03); # <= FLAGS
    login.sendall(bytes(login_packet))

    pb = PacketBuffer()
    id1 = accid = id2 = 0
    charip = ""
    charport = 0
    # Login server packet loop.
    while True:
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

    if charip == "127.0.0.1" and config.server != "127.0.0.1":
        charip = config.server

    char = socket.socket()
    char.connect((charip, charport))
    logger.info("Char connected")
    char_serv_packet = PacketOut(CMSG_CHAR_SERVER_CONNECT)
    char_serv_packet.write_int32(accid)
    char_serv_packet.write_int32(id1)
    char_serv_packet.write_int32(id2)
    char_serv_packet.write_int16(1) # this should match MIN_CLIENT_VERSION in tmwa/src/char/char.hpp
    char_serv_packet.write_int8(player_node.sex)
    char.sendall(bytes(char_serv_packet))
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
                count = (len(packet.data)-22) // 106
                for i in range(count):
                    player_node.id = packet.read_int32()
                    player_node.EXP = packet.read_int32()
                    player_node.MONEY = packet.read_int32()
                    packet.skip(62)
                    player_node.name = packet.read_string(24)
                    packet.skip(6)
                    slot = packet.read_int8()
                    packet.skip(1)
                    logger.info("Character information recieved:")
                    logger.info("Name: %s, Id: %s, EXP: %s, MONEY: %s", \
                    player_node.name, player_node.id, player_node.EXP, player_node.MONEY)
                    if slot == character:
                        break

                char_select_packet = PacketOut(CMSG_CHAR_SELECT)
                char_select_packet.write_int8(character)
                char.sendall(bytes(char_select_packet))

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

    if mapip == "127.0.0.1" and charip != "127.0.0.1":
        mapip = charip

    beingManager.container[player_node.id] = Being(player_node.id, 42)
    global mapserv
    mapserv = socket.socket()
    mapserv.connect((mapip, mapport))
    logger.info("Map connected")
    mapserv_login_packet = PacketOut(CMSG_MAP_SERVER_CONNECT)
    mapserv_login_packet.write_int32(accid)
    mapserv_login_packet.write_int32(player_node.id)
    mapserv_login_packet.write_int32(id1)
    mapserv_login_packet.write_int32(id2)
    mapserv_login_packet.write_int8(player_node.sex)
    mapserv.sendall(bytes(mapserv_login_packet))
    mapserv.recv(4)

    pb = PacketBuffer()
    shop_broadcaster.mapserv = mapserv
    db_manager.mapserv = mapserv
    db_manager.start()
    ircbot.broadcastFunc = broadcast_from_irc
    ircbot.start()

    # Functionality for systemd watchdog keepalives
    last_sd_notify = None
    def notify_systemd():
        sd.notify("WATCHDOG=1")
        return time.time()
    # READY=1 is required once when the unit is Type=notify; without it
    # systemd treats startup as never having finished and kills the
    # service after TimeoutStartSec.
    sd.notify("READY=1")
    last_sd_notify = notify_systemd()

    last_online_request = 0

    # Map server packet loop
    print("Entering map packet loop\n")
    while True:
        data = mapserv.recv(2048)
        if not data:
            break
        pb.feed(data)

        # If it's been more than five seconds since we last notified systemd that we're still alive, do so now.
        if time.time() - last_sd_notify > sd_min_keepalive_rate:
            last_sd_notify = notify_systemd()

        if time.time() - last_online_request > config.online_interval:
            mapserv.sendall(request_online_list())
            last_online_request = time.time()

        # For unfinished trades - one way to distrupt service would be leaving a trade active.
        if trader_state.Trading.locked():
            if time.time() - trader_state.timer > 2*60:
                logger.info("Trade Cancelled - Timeout.")
                trader_state.timer = time.time()
                mapserv.sendall(bytes(PacketOut(CMSG_TRADE_CANCEL_REQUEST)))

        for packet in pb:
            if packet.is_type(SMSG_MAP_LOGIN_SUCCESS): # connected
                logger.info("Map login success.")
                packet.skip(4)
                coord_data = packet.read_coord_dir()
                player_node.x = coord_data[0]
                player_node.y = coord_data[1]
                player_node.direction = coord_data[2]
                logger.info("Starting Postion: %s %s %s", player_node.map, player_node.x, player_node.y)
                mapserv.sendall(bytes(PacketOut(CMSG_MAP_LOADED))) # map loaded
                # A Thread to send a shop broadcast: also keeps the network active to prevent timeouts.
                shop_broadcaster.start()

            elif packet.is_type(SMSG_PVP_SET):
                packet.skip(12)

            elif packet.is_type(SMSG_PVP_MAP_MODE):
                packet.skip(2)

            elif packet.is_type(SMSG_QUEST_SET_VAR):
                packet.skip(6)

            elif packet.is_type(SMSG_QUEST_PLAYER_VARS):
                nb = (packet.read_int16() - 4) // 6
                for loop in range(nb):
                    packet.skip(6)

            elif packet.is_type(SMSG_ONLINE_LIST):
                length = packet.read_int16()
                count = (length - 4) // 31
                online = []
                for _ in range(count):
                    packet.skip(4) # account id
                    online.append(packet.read_string(24))
                    packet.skip(3) # level, gm level, gender
                db_manager.update_online_users(online)

            elif packet.is_type(SMSG_NPC_COMMAND):
                packet.skip(14)

            elif packet.is_type(SMSG_BEING_MOVE3):
                nb = (packet.read_int16() - 14) // 1
                packet.skip(10)
                for loop in range(nb):
                    packet.skip(1)

            elif packet.is_type(SMSG_MAP_MASK):
                packet.skip(8)

            elif packet.is_type(SMSG_MAP_MUSIC):
                nb = (packet.read_int16() - 4) // 1
                for loop in range(nb):
                    packet.skip(1)

            elif packet.is_type(SMSG_NPC_CHANGETITLE):
                nb = (packet.read_int16() - 10) // 1
                packet.skip(6)
                for loop in range(nb):
                    packet.skip(1)

            elif packet.is_type(SMSG_SCRIPT_MESSAGE):
                nb = (packet.read_int16() - 5) // 1
                packet.skip(1)
                for loop in range(nb):
                    packet.skip(1)

            elif packet.is_type(SMSG_PLAYER_CLIENT_COMMAND):
                nb = (packet.read_int16() - 4) // 1
                for loop in range(nb):
                    packet.skip(1)

            elif packet.is_type(SMSG_MAP_SET_TILES_TYPE):
                packet.skip(32)

            elif packet.is_type(SMSG_PLAYER_HP):
                packet.skip(8)

            elif packet.is_type(SMSG_PLAYER_HP_FULL):
                packet.skip(12)

            elif packet.is_type(SMSG_WHISPER):
                msg_len = packet.read_int16() - 26
                nick = packet.read_string(24)
                message = packet.read_raw_string(msg_len)
                # Clean up the logs.
                if nick != 'AuctionBot':
                    logger.info("Whisper: " + nick + ": " + message)
                process_whisper(nick, utils.remove_colors(message), mapserv)

            elif packet.is_type(SMSG_PLAYER_STAT_UPDATE_1):
                stat_type = packet.read_int16()
                value = packet.read_int32()
                if stat_type == 0x0018:
                    logger.info("Weight changed from %s/%s to %s/%s", \
                    player_node.WEIGHT, player_node.MaxWEIGHT, value, player_node.MaxWEIGHT)
                    player_node.WEIGHT = value
                elif stat_type == 0x0019:
                    logger.info("Max Weight: %s", value)
                    player_node.MaxWEIGHT = value

            elif packet.is_type(SMSG_PLAYER_STAT_UPDATE_2):
                stat_type = packet.read_int16()
                value = packet.read_int32()
                if stat_type == 0x0014:
                    logger.info("Money Changed from %s, to %s", player_node.MONEY, value)
                    player_node.MONEY = value

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
                    mapserv.sendall(bytes(requestName))

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
                logger.info("Player warped: %s %s %s", player_node.map, player_node.x, player_node.y)
                mapserv.sendall(bytes(PacketOut(CMSG_MAP_LOADED)))

            elif packet.is_type(SMSG_PLAYER_INVENTORY_ADD):
                item = Item()
                item.index = packet.read_int16() - inventory_offset
                item.amount = packet.read_int16()
                item.itemId = packet.read_int16()
                packet.skip(14)
                err = packet.read_int8()

                if err == 0:
                    if item.index in player_node.inventory:
                        player_node.inventory[item.index].amount += item.amount
                    else:
                        player_node.inventory[item.index] = item

                    logger.info("Picked up: %s, Amount: %s, Index: %s", ItemDB.getItem(item.itemId).name, str(item.amount), str(item.index))

            elif packet.is_type(SMSG_PLAYER_INVENTORY_REMOVE):
                index = packet.read_int16() - inventory_offset
                amount = packet.read_int16()

                logger.info("Remove item: %s, Amount: %s, Index: %s", ItemDB.getItem(player_node.inventory[index].itemId).name, str(amount), str(index))
                player_node.remove_item(index, amount)

            elif packet.is_type(SMSG_PLAYER_INVENTORY):
                player_node.inventory.clear() # Clear the inventory - incase of new index.
                packet.skip(2)
                number = (len(packet.data)-2) // 18
                for loop in range(number):
                    item = Item()
                    item.index = packet.read_int16() - inventory_offset
                    item.itemId = packet.read_int16()
                    packet.skip(2)
                    item.amount = packet.read_int16()
                    packet.skip(10)
                    player_node.inventory[item.index] = item

            elif packet.is_type(SMSG_PLAYER_EQUIPMENT):
                packet.read_int16()
                number = (len(packet.data)) // 20
                for loop in range(number):
                    item = Item()
                    item.index = packet.read_int16() - inventory_offset
                    item.itemId = packet.read_int16()
                    packet.skip(16)
                    item.amount = 1
                    player_node.inventory[item.index] = item

                logger.info("Inventory information received:")
                for item in player_node.inventory:
                    logger.info("Name: %s, Id: %s, Index: %s, Amount: %s.", \
                    ItemDB.getItem(player_node.inventory[item].itemId).name, \
                    player_node.inventory[item].itemId, item, player_node.inventory[item].amount)

                errorOccured = player_node.check_inventory(user_tree, sale_tree)
                if errorOccured:
                    global trading_enabled
                    logger.error(errorOccured)
                    logger.error("Inventory check failed; trading is disabled until this is resolved. The IRC bridge will keep relaying.")
                    trading_enabled = False
                    shop_broadcaster.stop()
                else:
                    logger.info("Inventory Check Passed.")
                    trading_enabled = True

            elif packet.is_type(SMSG_TRADE_REQUEST):
                name = packet.read_string(24)
                logger.info("Trade request: " + name)
                mapserv.sendall(trade_respond(False))

            elif packet.is_type(SMSG_TRADE_RESPONSE):
                response = packet.read_int8()
                time.sleep(0.2)
                if response == 0:
                    logger.info("Trade response: Too far away.")
                    if trader_state.item:
                        mapserv.sendall(whisper(trader_state.item.player, "You are too far away."))
                    elif trader_state.money:
                        mapserv.sendall(whisper(trader_state.money, "You are too far away."))
                    trader_state.reset()

                elif response == 3:
                    logger.info("Trade response: Trade accepted.")
                    if trader_state.item:
                        if trader_state.item.get == 1: # add
                            mapserv.sendall(bytes(PacketOut(CMSG_TRADE_ADD_COMPLETE)))
                        elif trader_state.item.get == 0: # buy
                            if player_node.find_inventory_index(trader_state.item.id) != -10:
                                mapserv.sendall(trade_add_item(player_node.find_inventory_index(trader_state.item.id), trader_state.item.amount))
                                mapserv.sendall(bytes(PacketOut(CMSG_TRADE_ADD_COMPLETE)))
                                if trader_state.item.price == 0: # getback
                                    mapserv.sendall(bytes(PacketOut(CMSG_TRADE_OK)))
                                    trader_state.complete = 1
                            else:
                                mapserv.sendall(bytes(PacketOut(CMSG_TRADE_CANCEL_REQUEST)))
                                logger.info("Trade response: Trade accepted (buy) - the item could not be added.")
                                mapserv.sendall(whisper(trader_state.item.player, "Sorry, a problem has occured."))

                    elif trader_state.money: # money
                        amount = int(user_tree.get_user(trader_state.money).get('money'))
                        mapserv.sendall(trade_add_item(0-inventory_offset, amount))
                        mapserv.sendall(bytes(PacketOut(CMSG_TRADE_ADD_COMPLETE)))
                        mapserv.sendall(bytes(PacketOut(CMSG_TRADE_OK)))

                else:
                    logger.info("Trade response: Trade cancelled")
                    trader_state.reset()

            elif packet.is_type(SMSG_TRADE_ITEM_ADD):
                amount = packet.read_int32()
                item_id = packet.read_int16()
                if trader_state.item and trader_state.money == 0:
                    if  trader_state.item.get == 1: # add
                        if amount == trader_state.item.amount and item_id == trader_state.item.id:
                            trader_state.complete = 1
                            mapserv.sendall(bytes(PacketOut(CMSG_TRADE_OK)))
                        elif item_id == 0 and amount > 0:
                            mapserv.sendall(whisper(trader_state.item.player, "Why are you adding money?!?!"))
                            mapserv.sendall(bytes(PacketOut(CMSG_TRADE_CANCEL_REQUEST)))
                        else:
                            mapserv.sendall(whisper(trader_state.item.player, "Please check the correct item or quantity has been added."))
                            mapserv.sendall(bytes(PacketOut(CMSG_TRADE_CANCEL_REQUEST)))

                    elif trader_state.item.get == 0: # buy
                        if item_id == 0 and amount == trader_state.item.price * trader_state.item.amount:
                            mapserv.sendall(bytes(PacketOut(CMSG_TRADE_OK)))
                            trader_state.complete = 1
                        elif item_id == 0 and amount != trader_state.item.price * trader_state.item.amount:
                            trader_state.complete = 0
                        else:
                            mapserv.sendall(whisper(trader_state.item.player, "Don't give me your itenz."))
                            mapserv.sendall(bytes(PacketOut(CMSG_TRADE_CANCEL_REQUEST)))

                elif trader_state.money: # money
                    mapserv.sendall(whisper(trader_state.money, "Don't give me your itenz."))
                    mapserv.sendall(bytes(PacketOut(CMSG_TRADE_CANCEL_REQUEST)))

                logger.info("Trade item add: ItemId:%s Amount:%s", item_id, amount)
                # Note item_id = 0 is money

            elif packet.is_type(SMSG_TRADE_ITEM_ADD_RESPONSE):
                index = packet.read_int16() - inventory_offset
                amount = packet.read_int16()
                response = packet.read_int8()

                if response == 0:
                    logger.info("Trade item add response: Successfully added item.")
                    if trader_state.item:
                        if trader_state.item.get == 0 and index != 0-inventory_offset: # Make sure the correct item is given!
                            # index & amount are Always 0
                            if player_node.inventory[index].itemId != trader_state.item.id or \
                                amount != trader_state.item.amount:
                                logger.info(f"Index: {index}")
                                logger.info(f"P.ItemId: {player_node.inventory[index].itemId}")
                                logger.info(f"T.ItemId: {trader_state.item.id}")
                                logger.info(f"P.Amount: {amount}")
                                logger.info(f"T.Amount: {trader_state.item.amount}")
                                #mapserv.sendall(bytes(PacketOut(CMSG_TRADE_CANCEL_REQUEST)))

                    # If Trade item add successful - Remove the item from the inventory state.
                    if index != 0: # If it's not money
                        logger.info("Remove item: %s, Amount: %s, Index: %s", ItemDB.getItem(player_node.inventory[index].itemId).name, str(amount),str(index))
                        player_node.remove_item(index, amount)
                    else:
                        # The money amount isn't actually sent by the server - odd?!?!?.
                        if trader_state.money:
                            logger.info("Trade: Money Added.")
                            trader_state.complete = 1

                elif response == 1:
                    logger.info("Trade item add response: Failed - player overweight.")
                    mapserv.sendall(bytes(PacketOut(CMSG_TRADE_CANCEL_REQUEST)))
                    if trader_state.item:
                        mapserv.sendall(whisper(trader_state.item.player, "You are carrying too much weight. Unload and try again."))
                elif response == 2:
                    if trader_state.item:
                        mapserv.sendall(whisper(trader_state.item.player, "You have no free slots."))
                    logger.info("Trade item add response: Failed - No free slots.")
                    mapserv.sendall(bytes(PacketOut(CMSG_TRADE_CANCEL_REQUEST)))
                else:
                    logger.info("Trade item add response: Failed - unknown reason.")
                    mapserv.sendall(bytes(PacketOut(CMSG_TRADE_CANCEL_REQUEST)))
                    if trader_state.item:
                        mapserv.sendall(whisper(trader_state.item.player, "Sorry, a problem has occured."))

            elif packet.is_type(SMSG_TRADE_OK):
                is_ok = packet.read_int8() # 0 is ok from self, and 1 is ok from other
                if is_ok == 0:
                    logger.info("Trade OK: Self.")
                else:
                    if trader_state.complete:
                        mapserv.sendall(bytes(PacketOut(CMSG_TRADE_OK)))
                    else:
                        mapserv.sendall(bytes(PacketOut(CMSG_TRADE_CANCEL_REQUEST)))
                        if trader_state.item:
                            mapserv.sendall(whisper(trader_state.item.player, "Trade Cancelled: Please check the traded items or money."))

                    logger.info("Trade Ok: Partner.")

            elif packet.is_type(SMSG_TRADE_CANCEL):
                trader_state.reset()
                logger.info("Trade Cancel.")

            elif packet.is_type(SMSG_TRADE_COMPLETE):
                commitMessage=""
                # The sale_tree is only ammended after a complete trade packet.
                if trader_state.item and trader_state.money == 0:
                    if trader_state.item.get == 1: # !add
                        sale_tree.add_item(trader_state.item.player, trader_state.item.id, trader_state.item.amount, trader_state.item.price)
                        user_tree.get_user(trader_state.item.player).set('used_stalls', \
                            str(int(user_tree.get_user(trader_state.item.player).get('used_stalls')) + 1))
                        user_tree.get_user(trader_state.item.player).set('last_use', str(time.time()))
                        commitMessage = "Add"

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
                            ItemLog.add_item(int(item.get('itemId')), trader_state.item.amount, trader_state.item.price * trader_state.item.amount, item.get('name'))
                        commitMessage = "Buy or Getback"

                elif trader_state.money and trader_state.item == 0: # !money
                    user_tree.get_user(trader_state.money).set('money', str(0))
                    commitMessage = "Money"

                sale_tree.save()
                user_tree.save()
                tradey.saveData(commitMessage)

                trader_state.reset()
                logger.info("Trade Complete.")

                errorOccured = player_node.check_inventory(user_tree, sale_tree)
                if errorOccured:
                    logger.error(errorOccured)
                    logger.error("Post-trade inventory check failed; trading is disabled until this is resolved. The IRC bridge will keep relaying.")
                    trading_enabled = False
                    shop_broadcaster.stop()
            else:
                pass

    # On Disconnect/Exit
    logger.info("Server disconnect.")
    db_manager.stop()
    shop_broadcaster.stop()
    ircbot.stop()
    mapserv.close()

if __name__ == '__main__':
    main()
