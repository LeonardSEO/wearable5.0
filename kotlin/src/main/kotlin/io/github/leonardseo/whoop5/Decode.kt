package io.github.leonardseo.whoop5

/**
 * Decoded WHOOP 5/MG packets. Twin of `python/whoop5/decode.py` and the Swift `Whoop5Decoder`; parity is
 * pinned by `fixtures/golden.json`. Unknown layouts are kept raw, never dropped or zero-filled.
 * Unsigned wire values are widened (u8/u16 to Int, u32 to Long).
 */
sealed class Whoop5Packet {
    data class CommandResponse(val sequence: Int, val command: Int, val originSequence: Int, val result: Int,
                               val body: ByteArray) : Whoop5Packet() {
        val isPending: Boolean get() = result == 2
        val commandName: String get() = Whoop5Schema.commandName(command)
        /** Field-exact GET_DATA_RANGE decode on the final SUCCESS reply; null for PENDING or a short body. */
        val dataRange: DataRange? get() = if (command == 34 && result == 1) DataRange.parse(body) else null
        /** GET_CLOCK_DEPRECATED (11) reply: strap clock as Unix seconds. */
        val deprecatedClockUnix: Long? get() = if (command == 11 && result == 1 && body.size >= 4) body.u32(0) else null
    }
    data class RealtimeHR(val unix: Long, val heartRate: Int, val rrMs: List<Int>) : Whoop5Packet()
    data class Event(val number: Int, val unix: Long, val payload: ByteArray) : Whoop5Packet() {
        val name: String get() = Whoop5Schema.eventName(number)
        /** BATTERY_LEVEL (3): state of charge in % (tenths on the wire) and cell voltage in mV. */
        val battery: Pair<Double, Int>? get() =
            if (number == 3 && payload.size >= 7) Pair(payload.u16(1) / 10.0, payload.u16(5)) else null
    }
    data class Metadata(val type: Int, val unix: Long?, val subsec: Int?, val endToken: ByteArray?) : Whoop5Packet() {
        val trimCursor: Long? get() = endToken?.u32(0)
    }
    data class Console(val sequence: Int, val text: String) : Whoop5Packet()
    data class Record(val header: RecordHeader, val record: Whoop5Record) : Whoop5Packet()
    data class ImuStream(val packetType: Int, val imu: IMU) : Whoop5Packet()
    data class Other(val packetType: Int, val body: ByteArray) : Whoop5Packet()
}

data class RecordHeader(val packetType: Int, val layout: Int, val marker: Int, val recordIndex: Long, val unix: Long,
                        val subsec: Int)

sealed class Whoop5Record {
    data class Biometric(val r18: R18) : Whoop5Record()
    data class Optical(val blocks: List<OpticalBlock>) : Whoop5Record()
    data class Imu(val imu: IMU) : Whoop5Record()
    data class CompactOptical(val burstCounter: Int, val samples: List<Long>, val motionSummary: Float, val status: Int,
                              val onWristRaw: Int, val acceptanceRaw: Int) : Whoop5Record()
    data class QueuedChannel(val innerVersion: Int, val innerSubversion: Int, val channel: Int?, val metadata: Int?,
                             val sampleBits: List<Long>) : Whoop5Record()
    data class Ecg(val isRaw: Boolean, val quality: Int, val stateBits: Int, val sampleCount: Int, val samples: List<Int>,
                   val flag6: List<Int>, val flag7: List<Int>, val leadI: List<Int>, val leadQ: List<Int>) : Whoop5Record()
    data class Unknown(val body: ByteArray) : Whoop5Record()
    data class UnexpectedLength(val body: ByteArray) : Whoop5Record()
}

data class R18(
    val heartRate: Int, val rrMs: List<Int>, val hrFlags: Int, val altHeartRate: Int, val dynamicAccelG: Float,
    val gravityG: Triple<Float, Float, Float>, val stepCounter: Int, val cadenceRaw: Int, val hwStepCounter: Int,
    val activityClass: Int, val tempAux1Raw: Int, val tempAux2Raw: Int, val skinTempRaw: Int, val stateBits: Int,
    val spo2Byte82: Int,
) {
    /** Skin temperature in °C (raw / 100), null outside the 5–45 °C plausibility window. */
    val skinTempC: Double? get() = scaled(skinTempRaw.toDouble(), 0.01, 5.0, 45.0)
    val tempAux1C: Double? get() = scaled(tempAux1Raw.toDouble(), 0.1, 0.0, 60.0)
    val tempAux2C: Double? get() = scaled(tempAux2Raw.toDouble(), 0.1, 0.0, 60.0)
    /** Band motion/rest state `(byte81 >> 4) & 3`: band state, not a sleep stage. */
    val bandState: String get() = listOf("WAKE", "STILL", "SLEEP", "UP")[(stateBits shr 4) and 3]
    /**
     * SpO2 in % (**experimental**): byte 82 when it holds 70..100. The strap fills it during scheduled 30 s
     * windows every 20 min while asleep; other values are status codes, 0 means no measurement.
     */
    val spo2Percent: Int? get() = if (spo2Byte82 in 70..100) spo2Byte82 else null

    private fun scaled(raw: Double, k: Double, lo: Double, hi: Double): Double? {
        val v = Math.round(raw * k * 10_000) / 10_000.0
        return if (v in lo..hi) v else null
    }
}

data class OpticalBlock(
    val count: Int, val sourceA: Int, val driveA: Int, val sourceB: Int, val driveB: Int, val detectorA: Int,
    val rangeA: Long, val offsetA: Int, val detectorB: Int, val rangeB: Long, val offsetB: Int,
    val slotA: List<Int>, val slotB: List<Int>,
)

data class IMU(val accel: List<List<Int>>, val gyro: List<List<Int>>) {
    val accelCount: Int get() = accel.firstOrNull()?.size ?: 0
    val gyroCount: Int get() = gyro.firstOrNull()?.size ?: 0
}

/** GET_DATA_RANGE (34) final 65-byte body. Page cursors, not timestamps, describe the backlog. */
data class DataRange(val readPage: Long, val writePage: Long, val trimPage: Long, val totalPages: Long,
                     val newestClock: Long) {
    /** Ring backlog in pages: `write - trim`, wrapping through `total`. null for an implausible frame. */
    val pagesBehind: Long? get() {
        if (totalPages <= 0 || writePage >= totalPages || trimPage >= totalPages) return null
        return if (writePage >= trimPage) writePage - trimPage else (totalPages - trimPage) + writePage
    }
    /** Unix seconds of the last written page; null for the 0 / 0xFFFFFFFF sentinels. */
    val newestUnix: Long? get() = if (newestClock == 0L || newestClock == 0xFFFFFFFFL) null else newestClock

    companion object {
        fun parse(body: ByteArray): DataRange? = if (body.size < 65) null else
            DataRange(body.u32(5), body.u32(9), body.u32(13), body.u32(21), body.u32(57))
    }
}

object Whoop5Decoder {
    /** BLE-spec 1/1024 s ticks to ms. Not used for WHOOP 5/MG, which sends R-R in milliseconds. */
    fun rrTicksToMs(ticks: Int): Int = (ticks * 1000 + 512) / 1024

    private val minEnd = mapOf(36 to 13, 40 to 18, 48 to 16, 43 to 21, 47 to 21)
    private val expectedLength = mapOf(16 to 1584, 17 to 240, 18 to 124, 20 to 2140, 21 to 1244, 26 to 88, 22 to 188)

    /** Validate and decode one complete frame. Throws [Whoop5Framing.FrameException] on an invalid frame. */
    fun decode(raw: ByteArray): Whoop5Packet {
        Whoop5Framing.validate(raw)
        val end = raw.size - 4
        val type = raw.u8(8)
        minEnd[type]?.let { if (end < it) return Whoop5Packet.Other(type, raw.copyOfRange(8, end)) }
        return when (type) {
            36 -> Whoop5Packet.CommandResponse(raw.u8(9), raw.u8(10), raw.u8(11), raw.u8(12), raw.copyOfRange(13, end))
            40 -> Whoop5Packet.RealtimeHR(raw.u32(10), raw.u8(16), rr(raw, 18, raw.u8(17), 64, end))
            48 -> Whoop5Packet.Event(raw.u8(10), raw.u32(12), payload(raw, end))
            50 -> if (end >= 21) {
                var p = payload(raw, end).drop(1)
                while (p.isNotEmpty() && p.last() == 0.toByte()) p = p.dropLast(1)  // each fragment is NUL-terminated
                // Latin-1, byte for byte, to match the Python reference on non-ASCII bytes.
                Whoop5Packet.Console(raw.u8(9), String(p.toByteArray(), Charsets.ISO_8859_1))
            } else Whoop5Packet.Other(type, raw.copyOfRange(8, end))
            49 -> Whoop5Packet.Metadata(
                raw.u8(10), if (end >= 15) raw.u32(11) else null, if (end >= 17) raw.u16(15) else null,
                if (raw.u8(10) == 2 && end >= 29) raw.copyOfRange(21, 29) else null)
            43, 47 -> Whoop5Packet.Record(
                RecordHeader(type, raw.u8(9), raw.u8(10), raw.u32(11), raw.u32(15), raw.u16(19)),
                record(raw, raw.u8(9), end))
            51, 52 -> Whoop5Packet.ImuStream(type, imuStream(raw, end))
            else -> Whoop5Packet.Other(type, raw.copyOfRange(8, end))
        }
    }

    /** Event/console payload: `length` (u16 @18) bytes from offset 20, clamped to the CRC boundary. */
    internal fun payload(raw: ByteArray, end: Int): ByteArray =
        if (end < 20) ByteArray(0) else raw.copyOfRange(20, minOf(20 + raw.u16(18), end))

    private fun rr(raw: ByteArray, offset: Int, count: Int, limit: Int, end: Int): List<Int> {
        val out = mutableListOf<Int>()
        for (i in 0 until minOf(count, limit)) {
            val o = offset + 2 * i
            if (o + 2 > end) break
            val t = raw.u16(o)
            if (t != 0) out.add(t)  // WHOOP 5/MG sends R-R in milliseconds
        }
        return out
    }

    private fun record(raw: ByteArray, layout: Int, end: Int): Whoop5Record {
        val body = raw.copyOfRange(8, end)
        val len = expectedLength[layout] ?: return Whoop5Record.Unknown(body)
        if (raw.size != len) return Whoop5Record.UnexpectedLength(body)
        return when (layout) {
            18 -> Whoop5Record.Biometric(R18(
                raw.u8(22), rr(raw, 24, raw.u8(23), 4, end), raw.u8(36), raw.u8(37), raw.f32(41),
                Triple(raw.f32(45), raw.f32(49), raw.f32(53)), raw.u16(57), raw.u16(59), raw.u16(61), raw.u8(63),
                raw.i16(69), raw.i16(71), raw.u16(73), raw.u8(81), raw.u8(82)))
            20 -> Whoop5Record.Optical(listOf(26, 448, 870, 1292, 1714).map { b ->
                val n = if (raw.u8(b) <= 50) raw.u8(b) else 0
                OpticalBlock(raw.u8(b), raw.u8(b + 1), raw.u16(b + 2), raw.u8(b + 4), raw.u16(b + 5), raw.u8(b + 7),
                    raw.u32(b + 8), raw.i16(b + 12), raw.u8(b + 14), raw.u32(b + 15), raw.i16(b + 19),
                    List(n) { raw.i32(b + 21 + 4 * it) }, List(n) { raw.i32(b + 221 + 4 * it) })
            })
            21 -> {
                val na = raw.u16(24); val ng = raw.u16(630)
                if (na > 100 || ng > 100) return Whoop5Record.Unknown(body)
                fun col(o: Int, n: Int) = List(n) { raw.i16(o + 2 * it) }
                Whoop5Record.Imu(IMU(listOf(col(28, na), col(228, na), col(428, na)),
                    listOf(col(640, ng), col(840, ng), col(1040, ng))))
            }
            26 -> {
                val s = mutableListOf(raw.u32(23))
                for (i in 0 until 24) s.add(s.last() + raw.i16(27 + 2 * i))
                Whoop5Record.CompactOptical(raw.u16(21), s, raw.f32(75), raw.u16(79), raw.u8(81), raw.u8(82))
            }
            16, 17 -> {
                val n = raw.u16(32); val isRaw = layout == 16
                if (n > (if (isRaw) 500 else 100)) return Whoop5Record.Unknown(body)
                val samples = mutableListOf<Int>(); val f6 = mutableListOf<Int>(); val f7 = mutableListOf<Int>()
                var li = emptyList<Int>(); var lq = emptyList<Int>()
                if (isRaw) {
                    for (i in 0 until n) {
                        val o = 34 + 3 * i
                        val v = ((raw.u8(o) and 0x03) shl 16) or (raw.u8(o + 1) shl 8) or raw.u8(o + 2)
                        samples.add(if (v >= 131_072) v - 262_144 else v)
                        f6.add((raw.u8(o) shr 6) and 1); f7.add((raw.u8(o) shr 7) and 1)
                    }
                    val k = minOf(raw.u8(1534), 11)
                    li = List(k) { raw.i16(1535 + 2 * it) }; lq = List(k) { raw.i16(1557 + 2 * it) }
                } else {
                    for (i in 0 until n) samples.add(raw.i16(34 + 2 * i))
                }
                Whoop5Record.Ecg(isRaw, raw.u8(21), raw.u8(22), n, samples, f6, f7, li, lq)
            }
            22 -> {
                val v = raw.u8(21)
                if (v != 9) Whoop5Record.QueuedChannel(v, raw.u8(22), null, null, emptyList())
                else {
                    val bits = mutableListOf(raw.u32(31))
                    for (i in 0 until 49) bits.add(bits.last() + raw.i16(35 + 2 * i))
                    Whoop5Record.QueuedChannel(v, raw.u8(22), raw.u8(141), raw.u16(137), bits.map { it and 0xFFFFFFFFL })
                }
            }
            else -> Whoop5Record.Unknown(body)
        }
    }

    private fun imuStream(raw: ByteArray, end: Int): IMU {
        if (end < 28) return IMU(emptyList(), emptyList())
        val na = raw.u16(24); val ng = raw.u16(26)
        if (28 + 6 * na + 6 * ng > end) return IMU(emptyList(), emptyList())
        var o = 28
        fun col(n: Int): List<Int> { val c = List(n) { raw.i16(o + 2 * it) }; o += 2 * n; return c }
        val a = listOf(col(na), col(na), col(na))
        val g = listOf(col(ng), col(ng), col(ng))
        return IMU(a, g)
    }
}
