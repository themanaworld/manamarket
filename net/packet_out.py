from .packet import *
from .protocol import *

def emote(emoteId):
    emote_packet = PacketOut(CMSG_PLAYER_EMOTE)
    emote_packet.write_int8(emoteId)
    return bytes(emote_packet)

def whisper(nick, message):
    if isinstance(message, bytes):
        msg_bytes = message
    else:
        msg_bytes = message.encode('utf-8')
    whisp_packet = PacketOut(CMSG_CHAT_WHISPER)
    whisp_packet.write_int16(len(msg_bytes) + 28)
    whisp_packet.write_string(nick, 24)
    whisp_packet.write_string(msg_bytes, len(msg_bytes))
    return bytes(whisp_packet)

def chat(text):
    chat_packet = PacketOut(CMSG_CHAT_MESSAGE)
    mes = player_node.name + " : " + text
    mes_bytes = mes.encode('utf-8')
    chat_packet.write_int16(len(mes_bytes) + 4 + 1)
    chat_packet.write_string(mes_bytes, len(mes_bytes) + 1)
    return bytes(chat_packet)

def sit(val):
    sit_packet = PacketOut(CMSG_PLAYER_CHANGE_ACT)
    sit_packet.write_int32(0)
    if val == True:
        sit_packet.write_int8(2)
    else:
        sit_packet.write_int8(3)
    return bytes(sit_packet)

def trade_request(being_id):
    trade_req_packet = PacketOut(CMSG_TRADE_REQUEST)
    trade_req_packet.write_int32(being_id)
    return bytes(trade_req_packet)

def trade_respond(accept):
    trade_respond_packet = PacketOut(CMSG_TRADE_RESPONSE)
    if accept == True:
        trade_respond_packet.write_int8(3)
    elif accept == False:
        trade_respond_packet.write_int8(4)
    return bytes(trade_respond_packet)

def trade_add_item(item_index, amount):
    trade_add_packet = PacketOut(CMSG_TRADE_ITEM_ADD_REQUEST)
    trade_add_packet.write_int16(item_index + inventory_offset)
    trade_add_packet.write_int32(amount)
    return bytes(trade_add_packet)
