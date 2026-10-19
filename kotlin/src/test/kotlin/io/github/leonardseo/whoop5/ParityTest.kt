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
    private fun Any?.lng(): Long? = (this as? Number)?.toLong()
    private fun Any?.ints(): List<Int>? = (this as? List<*>)?.map { (it as Number).toInt() }

    @Suppress("UNCHECKED_CAST")
    private val vectors = MiniJson.parse(
        ParityTest::class.java.getResourceAsStream("/golden.json")!!.bufferedReader().readText()) as List<Map<String, Any?>>

    @Test fun goldenParity() {
        assertTrue(vectors.size >= 18)
        vectors.forEach { check(it) }
    }

    /** Opt-in: WHOOP5_CORPUS_GOLDEN=<vectors JSON built from the local corpus> runs every real frame. */
    @Test fun corpusParity() {
        val path = System.getenv("WHOOP5_CORPUS_GOLDEN") ?: return
        @Suppress("UNCHECKED_CAST")
        val corpus = MiniJson.parse(java.io.File(path).readText()) as List<Map<String, Any?>>
        corpus.forEach { check(it) }
        println("corpus parity: ${corpus.size} vectors checked")
    }

    private fun check(v: Map<String, Any?>) {
        run {
            val name = v["name"] as String
            @Suppress("UNCHECKED_CAST") val e = v["expected"] as Map<String, Any?>
            when (val p = Whoop5Decoder.decode(hex(v["hex"] as String))) {
                is Whoop5Packet.Record -> {
                    assertEquals(e["layout"].int(), p.header.layout, name)
                    assertEquals(e["unix_s"].lng(), p.header.unix, name)
                    e["record_index"]?.let { assertEquals((it as Number).toLong(), p.header.recordIndex, name) }
                    when (val r = p.record) {
                        is Whoop5Record.Biometric -> {
                            assertEquals(e["heart_rate"].int(), r.r18.heartRate, name)
                            assertEquals(e["rr_ms"].ints(), r.r18.rrMs, name)
                            assertEquals(e["skin_temp_c"].dbl(), r.r18.skinTempC, name)
                            assertEquals(e["band_state"], r.r18.bandState, name)
                            assertEquals(e["spo2_percent"].int(), r.r18.spo2Percent, name)
                            assertEquals(e["step_counter"].int(), r.r18.stepCounter, name)
                            assertEquals(e["temp_aux1_c"].dbl(), r.r18.tempAux1C, name)
                        }
                        is Whoop5Record.Imu -> {
                            assertEquals(e["gyro_z"].ints(), r.imu.gyro[2], name)
                            assertEquals(e["accel_x"].ints(), r.imu.accel[0], name)
                        }
                        is Whoop5Record.CompactOptical -> {
                            assertEquals(e["samples"].ints(), r.samples.map { it.toInt() }, name)
                            assertEquals(e["burst_counter"].int(), r.burstCounter, name)
                        }
                        is Whoop5Record.Ecg -> {
                            assertEquals(e["samples"].ints(), r.samples, name)
                            assertEquals(e["sample_count"].int(), r.sampleCount, name)
                            assertEquals(e["quality"].int(), r.quality, name)
                            if (r.isRaw) assertEquals(e["lead_i"].ints(), r.leadI, name)
                        }
                        else -> Unit  // R20/R22/raw records: header fields above are the parity surface
                    }
                }
                is Whoop5Packet.RealtimeHR -> assertEquals(e["rr_ms"].ints(), p.rrMs, name)
                is Whoop5Packet.CommandResponse -> {
                    assertEquals(e["command"].int(), p.command, name)
                    assertEquals(e["result"].int(), p.result, name)
                    assertEquals(e["pages_behind"].lng(), p.dataRange?.pagesBehind, name)
                    assertEquals(e["newest_unix"].lng(), p.dataRange?.newestUnix, name)
                }
                is Whoop5Packet.Event -> {
                    assertEquals(e["event_name"], p.name, name)
                    assertEquals(e["event"].int(), p.number, name)
                    e["payload_hex"]?.let { assertEquals(it, p.payload.joinToString("") { b -> "%02x".format(b) }, name) }
                    p.battery?.let { assertEquals(e["soc_percent"].dbl(), it.first, name); assertEquals(e["millivolts"].int(), it.second, name) }
                }
                is Whoop5Packet.Metadata -> {
                    assertEquals(e["meta_type"].int(), p.type, name)
                    assertEquals(e["trim_cursor"].lng(), p.trimCursor, name)
                    assertEquals(e["unix_s"].lng(), p.unix, name)
                }
                is Whoop5Packet.Console -> {
                    assertEquals(e["text"], p.text, name)
                    assertEquals(e["console_sequence"].int(), p.sequence, name)
                }
                is Whoop5Packet.Other, is Whoop5Packet.ImuStream ->
                    if (e.containsKey("packet_type")) assertEquals(e["packet_type"].int(), (p as? Whoop5Packet.Other)?.packetType ?: (p as Whoop5Packet.ImuStream).packetType, name)
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
