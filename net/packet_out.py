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

from packet import *
from protocol import *

def emote(emoteId):
    emote_packet = PacketOut(CMSG_PLAYER_EMOTE)
    emote_packet.write_int8(emoteId)
    return str(emote_packet)

def whisper(nick, message):
    whisp_packet = PacketOut(CMSG_CHAT_WHISPER)
    whisp_packet.write_int16(len(message) + 28)
    whisp_packet.write_string(nick, 24)
    whisp_packet.write_string(message, len(message))
    return str(whisp_packet)

def chat(text):
    chat_packet = PacketOut(CMSG_CHAT_MESSAGE)
    mes = player_node.name + " : " + text
    chat_packet.write_int16(len(mes) + 4 + 1)
    chat_packet.write_string(mes, len(mes) + 1)
    return str(chat_packet)

def sit(val):
    sit_packet = PacketOut(CMSG_PLAYER_CHANGE_ACT)
    sit_packet.write_int32(0)
    if val == True:
        sit_packet.write_int8(2)
    else:
        sit_packet.write_int8(3)
    return str(sit_packet)

def trade_request(being_id):
    trade_req_packet = PacketOut(CMSG_TRADE_REQUEST)
    trade_req_packet.write_int32(being_id)
    return str(trade_req_packet)

def trade_respond(accept):
    trade_respond_packet = PacketOut(CMSG_TRADE_RESPONSE)
    if accept == True:
        trade_respond_packet.write_int8(3)
    elif accept == False:
        trade_respond_packet.write_int8(4)
    return str(trade_respond_packet)

def trade_add_item(item_index, amount):
    trade_add_packet = PacketOut(CMSG_TRADE_ITEM_ADD_REQUEST)
    trade_add_packet.write_int16(item_index + inventory_offset)
    trade_add_packet.write_int32(amount)
    return str(trade_add_packet)

