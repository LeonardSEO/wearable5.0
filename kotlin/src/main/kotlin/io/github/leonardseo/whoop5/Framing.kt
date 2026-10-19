package io.github.leonardseo.whoop5

/**
 * Format-1 envelope for WHOOP 5/MG: CRCs, validation, command building and BLE reassembly.
 * Pure JVM, no Android or Bluetooth dependency. Twin of `python/whoop5/framing.py` and the Swift
 * `Whoop5Framing`; parity is pinned by `fixtures/golden.json`.
 */
object Whoop5Framing {
    const val SOF = 0xAA
    const val FORMAT1 = 0x01
    const val BODY_OFFSET = 8
    const val MIN_FRAME = 16
    const val MAX_FRAME = 4096

    fun crc16Modbus(data: ByteArray, from: Int = 0, to: Int = data.size): Int {
        var crc = 0xFFFF
        for (i in from until to) {
            crc = crc xor (data[i].toInt() and 0xFF)
            repeat(8) { crc = if (crc and 1 != 0) (crc ushr 1) xor 0xA001 else crc ushr 1 }
        }
        return crc
    }

    private val crc32Table = IntArray(256) { i ->
        var c = i
        repeat(8) { c = if (c and 1 != 0) 0xEDB88320.toInt() xor (c ushr 1) else c ushr 1 }
        c
    }

    fun crc32(data: ByteArray, from: Int = 0, to: Int = data.size): Long {
        var c = -1
        for (i in from until to) c = crc32Table[(c xor data[i].toInt()) and 0xFF] xor (c ushr 8)
        return (c.inv().toLong()) and 0xFFFFFFFFL
    }

    class FrameException(message: String) : Exception(message)

    /** Throws unless [raw] is exactly one complete, CRC-valid format-1 frame. */
    fun validate(raw: ByteArray) {
        if (raw.size < MIN_FRAME) throw FrameException("too short")
        if (raw.u8(0) != SOF || raw.u8(1) != FORMAT1) throw FrameException("not a format-1 frame")
        val declared = raw.u16(2)
        if (declared + 8 != raw.size) throw FrameException("length mismatch")
        if ((declared - 4) % 4 != 0) throw FrameException("body not 4-aligned")
        if (crc16Modbus(raw, 0, 6) != raw.u16(6)) throw FrameException("header CRC16 mismatch")
        if (crc32(raw, BODY_OFFSET, raw.size - 4) != raw.u32(raw.size - 4)) throw FrameException("body CRC32 mismatch")
    }

    /** A format-1 COMMAND (type 35) frame. Builds bytes only; sending is the caller's decision. */
    fun command(command: Int, args: ByteArray = ByteArray(0), sequence: Int = 0,
                destination: Int = 0x00, source: Int = 0x01): ByteArray {
        var bodyLen = 3 + args.size
        while (bodyLen % 4 != 0) bodyLen++
        val body = ByteArray(bodyLen)
        body[0] = 35; body[1] = sequence.toByte(); body[2] = command.toByte()
        args.copyInto(body, 3)
        val frame = ByteArray(8 + bodyLen + 4)
        frame[0] = SOF.toByte(); frame[1] = FORMAT1.toByte()
        frame.putU16(2, bodyLen + 4)
        frame[4] = destination.toByte(); frame[5] = source.toByte()
        frame.putU16(6, crc16Modbus(frame, 0, 6))
        body.copyInto(frame, 8)
        frame.putU32(8 + bodyLen, crc32(body))
        return frame
    }

    /** HISTORICAL_DATA_RESULT (23) for one committed chunk: `01` + the verbatim 8-byte HISTORY_END token. */
    fun historyAck(endToken: ByteArray, sequence: Int = 0): ByteArray? =
        if (endToken.size != 8) null else command(23, byteArrayOf(0x01) + endToken, sequence)

    /** The fixed CLIENT_HELLO (GET_HELLO revision 1, sequence 1). */
    val clientHello: ByteArray get() = command(145, byteArrayOf(0x01), 1)
}

/**
 * Joins BLE notification fragments into complete, CRC-valid frames. Only the first fragment of a large
 * record starts with SOF; a corrupt candidate costs one byte of resync, never a later frame.
 */
class Whoop5Reassembler {
    private var buffer = ByteArray(0)

    fun feed(chunk: ByteArray): List<ByteArray> {
        buffer += chunk
        val out = mutableListOf<ByteArray>()
        while (true) {
            val start = firstStart()
            if (start < 0) {
                buffer = if (buffer.isNotEmpty() && buffer.u8(buffer.size - 1) == Whoop5Framing.SOF)
                    byteArrayOf(Whoop5Framing.SOF.toByte()) else ByteArray(0)
                return out
            }
            buffer = buffer.copyOfRange(start, buffer.size)
            if (buffer.size < 4) return out
            val total = buffer.u16(2) + 8
            if (total < Whoop5Framing.MIN_FRAME || total > Whoop5Framing.MAX_FRAME) {
                buffer = buffer.copyOfRange(1, buffer.size); continue
            }
            if (buffer.size < total) return out
            val candidate = buffer.copyOfRange(0, total)
            buffer = try {
                Whoop5Framing.validate(candidate)
                out.add(candidate)
                buffer.copyOfRange(total, buffer.size)
            } catch (e: Whoop5Framing.FrameException) {
                buffer.copyOfRange(1, buffer.size)
            }
        }
    }

    private fun firstStart(): Int {
        for (i in 0 until buffer.size - 1) {
            if (buffer.u8(i) == Whoop5Framing.SOF && buffer.u8(i + 1) == Whoop5Framing.FORMAT1) return i
        }
        return -1
    }
}

internal fun ByteArray.u8(o: Int): Int = this[o].toInt() and 0xFF
internal fun ByteArray.u16(o: Int): Int = u8(o) or (u8(o + 1) shl 8)
internal fun ByteArray.i16(o: Int): Int = u16(o).toShort().toInt()
internal fun ByteArray.u32(o: Int): Long =
    (u8(o).toLong()) or (u8(o + 1).toLong() shl 8) or (u8(o + 2).toLong() shl 16) or (u8(o + 3).toLong() shl 24)
internal fun ByteArray.i32(o: Int): Int = u32(o).toInt()
internal fun ByteArray.f32(o: Int): Float = Float.fromBits(u32(o).toInt())
internal fun ByteArray.putU16(o: Int, v: Int) { this[o] = v.toByte(); this[o + 1] = (v ushr 8).toByte() }
internal fun ByteArray.putU32(o: Int, v: Long) { for (k in 0..3) this[o + k] = (v ushr (8 * k)).toByte() }
