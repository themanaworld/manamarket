"""Tests for the packet helper functions in net/packet_out.py.

The whisper byte-length test is a regression guard for the bytes/str split
introduced when porting to Python 3: the on-wire length field must equal the
UTF-8 byte count of the message, not the str char count.
"""
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from net.packet import PacketBuffer, PacketIn
from net.packet_out import (
    emote, whisper, sit, trade_request, trade_respond, trade_add_item,
)
from net.protocol import (
    CMSG_PLAYER_EMOTE, CMSG_CHAT_WHISPER, CMSG_PLAYER_CHANGE_ACT,
    CMSG_TRADE_REQUEST, CMSG_TRADE_RESPONSE, CMSG_TRADE_ITEM_ADD_REQUEST,
    inventory_offset,
)


def parse_one(wire):
    """Feed `wire` into a PacketBuffer and return the single resulting PacketIn."""
    pb = PacketBuffer()
    pb.feed(wire)
    pkts = list(pb)
    assert len(pkts) == 1, "expected exactly 1 packet, got %d" % len(pkts)
    return pkts[0]


class WhisperTests(unittest.TestCase):
    def test_returns_bytes(self):
        self.assertIsInstance(whisper("nick", "msg"), bytes)

    def test_packet_type_and_framing(self):
        wire = whisper("Bjorn", "hi")
        pkt = parse_one(wire)
        self.assertEqual(pkt.pkttype, CMSG_CHAT_WHISPER)

    def test_length_field_includes_payload(self):
        """The int16 length right after the type must equal len(wire)."""
        wire = whisper("Bjorn", "hi")
        # Bytes 2..4 are the length field for variable-length packets.
        wire_len = struct.unpack("<H", wire[2:4])[0]
        self.assertEqual(wire_len, len(wire))

    def test_utf8_message_byte_length(self):
        """Recent regression: the length field must reflect UTF-8 *byte* count.

        'café' is 4 chars but 5 bytes in UTF-8 — the on-wire length must use 5,
        not 4, otherwise the receiver loses a byte and desyncs.
        """
        wire = whisper("Bjorn", "café")
        wire_len = struct.unpack("<H", wire[2:4])[0]
        self.assertEqual(wire_len, len(wire))
        # 2 (type) + 2 (length) + 24 (nick) + 5 (utf-8 of "café") = 33
        self.assertEqual(len(wire), 33)

    def test_accepts_pre_encoded_bytes(self):
        """Some call sites (4144 selllist) hand whisper raw bytes."""
        wire = whisper("Bjorn", b"\xc3\xa9")  # 2 raw bytes
        wire_len = struct.unpack("<H", wire[2:4])[0]
        self.assertEqual(wire_len, len(wire))
        # 2 + 2 + 24 + 2 = 30
        self.assertEqual(len(wire), 30)

    def test_nick_field_zero_padded(self):
        wire = whisper("Bjorn", "hi")
        # Nick is at offset 4..28 (24 bytes), null-padded.
        nick_field = wire[4:28]
        self.assertEqual(nick_field, b"Bjorn".ljust(24, b"\0"))


class SimpleHelperTests(unittest.TestCase):
    def test_emote(self):
        wire = emote(7)
        self.assertIsInstance(wire, bytes)
        pkt = parse_one(wire)
        self.assertEqual(pkt.pkttype, CMSG_PLAYER_EMOTE)
        self.assertEqual(pkt.read_int8(), 7)

    def test_sit_true_writes_action_2(self):
        wire = sit(True)
        pkt = parse_one(wire)
        self.assertEqual(pkt.pkttype, CMSG_PLAYER_CHANGE_ACT)
        self.assertEqual(pkt.read_int32(), 0)
        self.assertEqual(pkt.read_int8(), 2)

    def test_sit_false_writes_action_3(self):
        wire = sit(False)
        pkt = parse_one(wire)
        pkt.skip(4)
        self.assertEqual(pkt.read_int8(), 3)

    def test_trade_request_writes_being_id(self):
        wire = trade_request(0xCAFEBEEF)
        pkt = parse_one(wire)
        self.assertEqual(pkt.pkttype, CMSG_TRADE_REQUEST)
        self.assertEqual(pkt.read_int32(), 0xCAFEBEEF)

    def test_trade_respond_accept_writes_3(self):
        wire = trade_respond(True)
        pkt = parse_one(wire)
        self.assertEqual(pkt.pkttype, CMSG_TRADE_RESPONSE)
        self.assertEqual(pkt.read_int8(), 3)

    def test_trade_respond_reject_writes_4(self):
        wire = trade_respond(False)
        pkt = parse_one(wire)
        self.assertEqual(pkt.read_int8(), 4)

    def test_trade_add_item_offsets_index(self):
        wire = trade_add_item(5, 100)
        pkt = parse_one(wire)
        self.assertEqual(pkt.pkttype, CMSG_TRADE_ITEM_ADD_REQUEST)
        self.assertEqual(pkt.read_int16(), 5 + inventory_offset)
        self.assertEqual(pkt.read_int32(), 100)


if __name__ == "__main__":
    unittest.main()
