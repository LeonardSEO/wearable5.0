import filecmp
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from whoop5 import synth  # noqa: E402
from whoop5.decode import decode_frame, rr_ticks_to_ms  # noqa: E402
from whoop5.framing import FrameError, Reassembler, build_command, crc16_modbus, validate  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")


class Framing(unittest.TestCase):
    def test_client_hello_is_reproduced_byte_for_byte(self):
        self.assertEqual(build_command(145, b"\x01", sequence=1).hex(), "aa0108000001e67123019101363e5c8d")

    def test_crc16_modbus_check_value(self):
        self.assertEqual(crc16_modbus(b"123456789"), 0x4B37)

    def test_rejects_corrupt_body(self):
        f = bytearray(synth.r18())
        f[30] ^= 1
        with self.assertRaises(FrameError):
            validate(bytes(f))

    def test_reassembles_fragments_and_skips_garbage(self):
        frames = [synth.r21(), synth.r18(), synth.realtime_hr()]
        stream = b"\x00\x13" + b"".join(frames)
        r = Reassembler()
        out = []
        for i in range(0, len(stream), 244):
            out += r.feed(stream[i:i + 244])
        self.assertEqual(out, frames)


class Records(unittest.TestCase):
    def test_r18(self):
        d = decode_frame(synth.r18())
        self.assertEqual((d["layout"], d["heart_rate"], d["rr_ms"]), (18, 58, [1000, 957]))
        self.assertEqual(d["skin_temp_c"], 34.12)
        self.assertEqual(d["step_counter"], 1234)
        self.assertEqual(d["band_state"], "SLEEP")
        self.assertAlmostEqual(d["gravity_z_g"], 1.0)

    def test_r18_out_of_range_temperature_is_none_but_raw_kept(self):
        d = decode_frame(synth.r18(skin_raw=0))
        self.assertIsNone(d["skin_temp_c"])
        self.assertEqual(d["skin_temp_c_raw"], 0)

    def test_r21(self):
        d = decode_frame(synth.r21(3))
        self.assertEqual(d["accel_x"], [100, 101, 102])
        self.assertEqual(d["gyro_z"], [600, 601, 602])

    def test_r26_clipped_deltas_accumulate(self):
        d = decode_frame(synth.r26())
        self.assertEqual(d["samples"][:5], [100000, 100005, 100002, 132769, 100001])
        self.assertEqual(len(d["samples"]), 25)

    def test_realtime_hr(self):
        d = decode_frame(synth.realtime_hr(61, (1000, 1100)))
        self.assertEqual((d["heart_rate"], d["rr_ms"]), (61, [977, 1074]))

    def test_data_range_pages_behind_and_newest(self):
        d = decode_frame(synth.data_range(write=120, trim=100))
        self.assertEqual(d["command_name"], "GET_DATA_RANGE")
        self.assertEqual(d["fields"]["pages_behind"], 20)
        self.assertEqual(d["fields"]["newest_unix"], 1_790_000_123)
        wrapped = decode_frame(synth.data_range(write=5, trim=131070))
        self.assertEqual(wrapped["fields"]["pages_behind"], 7)

    def test_data_range_sentinel_newest_is_none(self):
        d = decode_frame(synth.data_range(write=1, trim=1, newest=0xFFFFFFFF))
        self.assertIsNone(d["fields"]["newest_unix"])

    def test_event(self):
        self.assertEqual(decode_frame(synth.event(9))["event_name"], "WRIST_ON")

    def test_unknown_layout_is_preserved(self):
        d = decode_frame(synth.record(99, 64, {}))
        self.assertEqual(d["record"], "UNKNOWN_LAYOUT_99")
        self.assertIn("body_hex", d)

    def test_rr_rounding(self):
        self.assertEqual([rr_ticks_to_ms(t) for t in (1, 512, 1024)], [1, 500, 1000])


class Schema(unittest.TestCase):
    def test_packaged_schema_matches_canonical(self):
        self.assertTrue(filecmp.cmp(os.path.join(ROOT, "protocol", "whoop5_protocol.json"),
                                    os.path.join(ROOT, "python", "whoop5", "whoop5_protocol.json"), shallow=False))


# Real WHOOP 5 frames published as test vectors in ryanbr/noop (Whoop5HistoricalTests.swift),
# firmware 50.38.x. Used here only to cross-check offsets against hardware output.
REAL_R18 = ("aa01740001003fb12f1280733d8401b69f266a66460066025a0265020000000000007b0a8d656463ff0012163cf6a439bf"
            "2924fd3ed763fe3e3200aa000000000000000000f7000901f10b0007010c020c000000000000000000000000000000000000"
            "00000000000100656f1e1e0000009d61a7c00000003e862817")
REAL_R26 = ("aa015000010035412f1a80ad418401f0a3266aae470100c3c5050068faccfa8dfb46fc8bfd4cfebafedafe6dff56ffd5ff"
            "fbff37ff6afce5f9d7f8dffa5efc98fddbfe5afe84fe15ff5cff405fb33c50080101006cb67c17")
REAL_END = "aa011c00010023d1316a0284a3266a0a373d00000041b601001000000000000044d21e3d"
REAL_ACK = "aa0110000001e0d12300170141b6010010000000667da4fb"


class RealFrames(unittest.TestCase):
    def test_real_r18(self):
        d = decode_frame(bytes.fromhex(REAL_R18))
        self.assertEqual((d["heart_rate"], d["rr_ms"], d["skin_temp_c"], d["step_counter"]), (102, [588, 599], 30.57, 50))
        self.assertEqual(d["unix_s"], 1780916150)

    def test_real_r26(self):
        d = decode_frame(bytes.fromhex(REAL_R26))
        self.assertEqual(d["samples"][:3], [378307, 376875, 375543])
        self.assertEqual(d["burst_counter"], 1)

    def test_real_history_end_and_ack(self):
        from whoop5.decode import history_ack
        d = decode_frame(bytes.fromhex(REAL_END))
        self.assertEqual((d["meta_name"], d["trim_cursor"], d["unix_s"]), ("HISTORY_END", 112193, 1780917124))
        self.assertEqual(history_ack(bytes.fromhex(d["end_token_hex"]), 0).hex(), REAL_ACK)


if __name__ == "__main__":
    unittest.main()
