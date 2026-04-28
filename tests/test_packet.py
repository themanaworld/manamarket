"""Tests for the low-level wire codec in net/packet.py.

Critical because if framing or read/write encoding regresses, the bot will
silently desync from the server (mis-parsed packets, malformed sends).
"""
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from net.packet import PacketOut, PacketIn, PacketBuffer, packet_lengths


# Pick a packet id with a known fixed length for framing tests.
# packet_lengths[0x0095] = 30 (SMSG_BEING_NAME_RESPONSE).
FIXED_PKT_TYPE = 0x0095
FIXED_PKT_LEN = 30
assert packet_lengths[FIXED_PKT_TYPE] == FIXED_PKT_LEN


def make_fixed_packet():
    """Build a 30-byte SMSG_BEING_NAME_RESPONSE: header + int32 id + 24-byte name."""
    return struct.pack("<H", FIXED_PKT_TYPE) + b"\x01\x02\x03\x04" + b"Bjorn".ljust(24, b"\0")


class PacketOutWriteTests(unittest.TestCase):
    def test_init_emits_packet_id_int16(self):
        pkt = PacketOut(0x1234)
        self.assertEqual(bytes(pkt), b"\x34\x12")

    def test_write_int8(self):
        pkt = PacketOut(0)
        pkt.write_int8(0xAB)
        self.assertEqual(bytes(pkt), b"\x00\x00\xab")

    def test_write_int16_little_endian(self):
        pkt = PacketOut(0)
        pkt.write_int16(0xCAFE)
        self.assertEqual(bytes(pkt), b"\x00\x00\xfe\xca")

    def test_write_int32_little_endian(self):
        pkt = PacketOut(0)
        pkt.write_int32(0xDEADBEEF)
        self.assertEqual(bytes(pkt), b"\x00\x00\xef\xbe\xad\xde")

    def test_write_string_pads_with_nulls(self):
        pkt = PacketOut(0)
        pkt.write_string("hi", 5)
        self.assertEqual(bytes(pkt), b"\x00\x00hi\0\0\0")

    def test_write_string_accepts_bytes(self):
        pkt = PacketOut(0)
        pkt.write_string(b"hi", 5)
        self.assertEqual(bytes(pkt), b"\x00\x00hi\0\0\0")

    def test_write_string_encodes_utf8(self):
        pkt = PacketOut(0)
        pkt.write_string("café", 6)
        # 'é' is 2 bytes in UTF-8; total 5 bytes payload + 1 null pad
        self.assertEqual(bytes(pkt), b"\x00\x00caf\xc3\xa9\0")

    def test_write_coords_packs_three_bytes(self):
        pkt = PacketOut(0)
        pkt.write_coords(50, 75, 4)
        # 2 bytes header + 3 bytes coords
        self.assertEqual(len(bytes(pkt)), 5)


class PacketInReadTests(unittest.TestCase):
    def test_read_int8(self):
        pkt = PacketIn(b"\x42", 0)
        self.assertEqual(pkt.read_int8(), 0x42)
        self.assertEqual(pkt.pos, 1)

    def test_read_int16_little_endian(self):
        pkt = PacketIn(b"\xfe\xca", 0)
        self.assertEqual(pkt.read_int16(), 0xCAFE)

    def test_read_int32_little_endian(self):
        pkt = PacketIn(b"\xef\xbe\xad\xde", 0)
        self.assertEqual(pkt.read_int32(), 0xDEADBEEF)

    def test_read_string_strips_at_first_null(self):
        pkt = PacketIn(b"Bjorn\0\0\0\0\0", 0)
        self.assertEqual(pkt.read_string(10), "Bjorn")
        self.assertEqual(pkt.pos, 10)

    def test_read_string_no_null_returns_full(self):
        pkt = PacketIn(b"Bjornnnnn", 0)
        self.assertEqual(pkt.read_string(9), "Bjornnnnn")

    def test_read_string_decodes_utf8(self):
        pkt = PacketIn(b"caf\xc3\xa9\0\0", 0)
        self.assertEqual(pkt.read_string(7), "café")

    def test_read_raw_string_keeps_nulls_and_decodes(self):
        pkt = PacketIn(b"a\0b", 0)
        self.assertEqual(pkt.read_raw_string(3), "a\0b")

    def test_skip_advances_position(self):
        pkt = PacketIn(b"\x00" * 10, 0)
        pkt.skip(7)
        self.assertEqual(pkt.pos, 7)


class WireRoundTripTests(unittest.TestCase):
    """PacketOut -> PacketIn must round-trip every field exactly."""

    def test_int_round_trip(self):
        out = PacketOut(0x9999)
        out.write_int8(0xAB)
        out.write_int16(0xCAFE)
        out.write_int32(0xDEADBEEF)
        # Skip the 2-byte packet id at the front
        pin = PacketIn(bytes(out)[2:], 0x9999)
        self.assertEqual(pin.read_int8(), 0xAB)
        self.assertEqual(pin.read_int16(), 0xCAFE)
        self.assertEqual(pin.read_int32(), 0xDEADBEEF)

    def test_string_round_trip(self):
        out = PacketOut(0)
        out.write_string("Bjorn", 24)
        pin = PacketIn(bytes(out)[2:], 0)
        self.assertEqual(pin.read_string(24), "Bjorn")

    def test_utf8_string_round_trip(self):
        out = PacketOut(0)
        out.write_string("café", 24)
        pin = PacketIn(bytes(out)[2:], 0)
        self.assertEqual(pin.read_string(24), "café")

    def test_coord_dir_round_trip(self):
        out = PacketOut(0)
        out.write_coords(50, 75, 4)
        pin = PacketIn(bytes(out)[2:], 0)
        x, y, d = pin.read_coord_dir()
        self.assertEqual((x, y, d), (50, 75, 4))


class PacketBufferTests(unittest.TestCase):
    def test_empty_buffer_yields_nothing(self):
        pb = PacketBuffer()
        self.assertEqual(list(pb), [])

    def test_partial_packet_yields_nothing(self):
        """Until the full packet has been fed, iteration must not produce it."""
        pb = PacketBuffer()
        pb.feed(make_fixed_packet()[:10])  # half a packet
        self.assertEqual(list(pb), [])
        # Buffer kept the partial bytes for the next feed.
        self.assertEqual(len(pb.buff), 10)

    def test_completes_after_remaining_bytes_arrive(self):
        pb = PacketBuffer()
        full = make_fixed_packet()
        pb.feed(full[:10])
        self.assertEqual(list(pb), [])
        pb.feed(full[10:])
        pkts = list(pb)
        self.assertEqual(len(pkts), 1)
        self.assertEqual(pkts[0].pkttype, FIXED_PKT_TYPE)
        # Buffer fully drained.
        self.assertEqual(pb.buff, b"")

    def test_multiple_packets_in_one_feed(self):
        pb = PacketBuffer()
        pb.feed(make_fixed_packet() * 3)
        pkts = list(pb)
        self.assertEqual(len(pkts), 3)
        for pkt in pkts:
            self.assertEqual(pkt.pkttype, FIXED_PKT_TYPE)

    def test_variable_length_packet(self):
        """packet_lengths[type] == -1 means: read length from bytes 2..4."""
        # SMSG_WHISPER (0x0097) is variable-length.
        var_type = 0x0097
        self.assertEqual(packet_lengths[var_type], -1)
        # Build a 32-byte SMSG_WHISPER: 2-byte type + 2-byte length + 28 payload bytes.
        payload = b"x" * 28
        wire = struct.pack("<HH", var_type, 32) + payload
        pb = PacketBuffer()
        pb.feed(wire)
        pkts = list(pb)
        self.assertEqual(len(pkts), 1)
        self.assertEqual(pkts[0].pkttype, var_type)
        # The packet's data slice excludes the 2-byte type header.
        self.assertEqual(len(pkts[0].data), 30)

    def test_variable_length_partial_header(self):
        """For variable-length packets, even bytes 2-4 may not have arrived yet."""
        var_type = 0x0097
        pb = PacketBuffer()
        pb.feed(struct.pack("<H", var_type))  # only 2 bytes — length not yet known
        self.assertEqual(list(pb), [])

    def test_drop_advances_buffer(self):
        pb = PacketBuffer()
        pb.feed(b"abcdef")
        pb.drop(3)
        self.assertEqual(pb.buff, b"def")


if __name__ == "__main__":
    unittest.main()
