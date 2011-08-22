from packet import *
from protocol import *

def handle_stat_update_1(packet, player_node, logging):
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
    elif stat_type == 0x0018:
        logging.info("Weight changed from %s/%s to %s/%s", \
        player_node.WEIGHT, player_node.MaxWEIGHT, value, player_node.MaxWEIGHT)
        player_node.WEIGHT = value
    elif stat_type == 0x0019:
        logging.info("Max Weight: %s", value)
        player_node.MaxWEIGHT = value

