package io.github.leonardseo.whoop5

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** Decodes every vector in golden.json (written by `python/gen_golden.py`) and compares with the Python reference. */
class ParityTest {
    private fun hex(s: String) = ByteArray(s.length / 2) { s.substring(2 * it, 2 * it + 2).toInt(16).toByte() }
    private fun Any?.int(): Int? = (this as? Number)?.toInt()
    private fun Any?.dbl(): Double? = (this as? Number)?.toDouble()
    private fun Any?.ints(): List<Int>? = (this as? List<*>)?.map { (it as Number).toInt() }

    @Suppress("UNCHECKED_CAST")
    private val vectors = MiniJson.parse(
        ParityTest::class.java.getResourceAsStream("/golden.json")!!.bufferedReader().readText()) as List<Map<String, Any?>>

    @Test fun goldenParity() {
        assertTrue(vectors.size >= 18)
        for (v in vectors) {
            val name = v["name"] as String
            @Suppress("UNCHECKED_CAST") val e = v["expected"] as Map<String, Any?>
            when (val p = Whoop5Decoder.decode(hex(v["hex"] as String))) {
                is Whoop5Packet.Record -> {
                    assertEquals(e["layout"].int(), p.header.layout, name)
                    assertEquals(e["unix_s"].int()?.toLong(), p.header.unix, name)
                    when (val r = p.record) {
                        is Whoop5Record.Biometric -> {
                            assertEquals(e["heart_rate"].int(), r.r18.heartRate, name)
                            assertEquals(e["rr_ms"].ints(), r.r18.rrMs, name)
                            assertEquals(e["skin_temp_c"].dbl(), r.r18.skinTempC, name)
                            assertEquals(e["band_state"], r.r18.bandState, name)
                            assertEquals(e["spo2_percent"].int(), r.r18.spo2Percent, name)
                        }
                        is Whoop5Record.Imu -> assertEquals(e["gyro_z"].ints(), r.imu.gyro[2], name)
                        is Whoop5Record.CompactOptical -> assertEquals(e["samples"].ints(), r.samples.map { it.toInt() }, name)
                        is Whoop5Record.Ecg -> assertEquals(e["samples"].ints(), r.samples, name)
                        else -> error("unexpected record $name")
                    }
                }
                is Whoop5Packet.RealtimeHR -> assertEquals(e["rr_ms"].ints(), p.rrMs, name)
                is Whoop5Packet.CommandResponse -> {
                    assertEquals(e["pages_behind"].int()?.toLong(), p.dataRange?.pagesBehind, name)
                    assertEquals(e["newest_unix"].int()?.toLong(), p.dataRange?.newestUnix, name)
                }
                is Whoop5Packet.Event -> {
                    assertEquals(e["event_name"], p.name, name)
                    p.battery?.let { assertEquals(e["soc_percent"].dbl(), it.first, name); assertEquals(e["millivolts"].int(), it.second, name) }
                }
                is Whoop5Packet.Metadata -> assertEquals(e["trim_cursor"].int()?.toLong(), p.trimCursor, name)
                is Whoop5Packet.Console -> assertEquals(e["text"], p.text, name)
                else -> error("unexpected packet $name")
            }
        }
    }

    @Test fun helloAndAckAreByteExact() {
        assertEquals("aa0108000001e67123019101363e5c8d", Whoop5Framing.clientHello.joinToString("") { "%02x".format(it) })
        assertEquals("aa0110000001e0d12300170141b6010010000000667da4fb",
            Whoop5Framing.historyAck(hex("41b6010010000000"))!!.joinToString("") { "%02x".format(it) })
    }

    @Test fun experimental() {
        val rr = listOf(1000, 1010, 990, 1000, 1020, 1000, 990, 1010, 1000, 990, 1000, 1500)
        assertEquals(14.8323970, Whoop5Experimental.rmssdMs(rr)!!, 1e-5)
        assertNull(Whoop5Experimental.rmssdMs(listOf(1000, 1010)))
        assertTrue(Whoop5Schema.destructiveCommands.contains(29))
    }
}
