import Foundation

/// Decoded WHOOP 5/MG packets. Twin of `python/whoop5/decode.py`; parity is pinned by
/// `fixtures/golden.json`. Unknown layouts are kept raw, never dropped or zero-filled.
public enum Whoop5Packet: Equatable {
    case commandResponse(CommandResponse)
    case realtimeHR(RealtimeHR)
    case event(Event)
    case metadata(Metadata)
    case record(RecordHeader, Record)
    case imuStream(packetType: UInt8, IMU)
    case console(sequence: UInt8, text: String)
    case other(packetType: UInt8, body: [UInt8])
}

public struct RecordHeader: Equatable {
    public let packetType: UInt8, layout: UInt8, marker: UInt8
    public let recordIndex: UInt32, unix: UInt32, subsec: UInt16
}

public enum Record: Equatable {
    case biometric(R18)
    case optical(R20)
    case imu(IMU)
    case compactOptical(R26)
    case queuedChannel(R22)
    case ecg(ECG)
    case unknown(body: [UInt8])
    case unexpectedLength(body: [UInt8])
}

public struct R18: Equatable {
    public let heartRate: UInt8, rrMs: [Int], hrFlags: UInt8, altHeartRate: UInt8
    public let dynamicAccelG: Float, gravityG: (Float, Float, Float)
    public let stepCounter: UInt16, cadenceRaw: UInt16, hwStepCounter: UInt16, activityClass: UInt8
    public let tempAux1Raw: Int16, tempAux2Raw: Int16, skinTempRaw: UInt16
    public let stateBits: UInt8, sleepAdjacent82: UInt8

    /// Skin temperature in °C (raw / 100), nil outside the 5–45 °C plausibility window.
    public var skinTempC: Double? { Self.scaled(Double(skinTempRaw), 0.01, 5...45) }
    public var tempAux1C: Double? { Self.scaled(Double(tempAux1Raw), 0.1, 0...60) }
    public var tempAux2C: Double? { Self.scaled(Double(tempAux2Raw), 0.1, 0...60) }
    /// Band motion/rest state `(byte81 >> 4) & 3`: band state, not a sleep stage.
    public var bandState: String { ["WAKE", "STILL", "SLEEP", "UP"][Int((stateBits >> 4) & 3)] }

    static func scaled(_ raw: Double, _ k: Double, _ valid: ClosedRange<Double>) -> Double? {
        let v = (raw * k * 10_000).rounded() / 10_000
        return valid.contains(v) ? v : nil
    }

    public static func == (a: R18, b: R18) -> Bool {
        a.heartRate == b.heartRate && a.rrMs == b.rrMs && a.skinTempRaw == b.skinTempRaw
            && a.stepCounter == b.stepCounter && a.stateBits == b.stateBits && a.gravityG == b.gravityG
    }
}

public struct OpticalBlock: Equatable {
    public let count: UInt8, sourceA: UInt8, driveA: UInt16, sourceB: UInt8, driveB: UInt16
    public let detectorA: UInt8, rangeA: UInt32, offsetA: Int16, detectorB: UInt8, rangeB: UInt32, offsetB: Int16
    public let slotA: [Int32], slotB: [Int32]
}

public struct R20: Equatable { public let blocks: [OpticalBlock] }

public struct IMU: Equatable {
    public let accel: [[Int16]], gyro: [[Int16]]
    public var accelCount: Int { accel.first?.count ?? 0 }
    public var gyroCount: Int { gyro.first?.count ?? 0 }
}

public struct R26: Equatable {
    public let burstCounter: UInt16, samples: [Int64], motionSummary: Float, status: UInt16
    public let onWristRaw: UInt8, acceptanceRaw: UInt8
}

public struct R22: Equatable {
    public let innerVersion: UInt8, innerSubversion: UInt8
    /// v9 only.
    public let channel: UInt8?, metadata: UInt16?, sampleBits: [UInt32]
}

/// MG ECG: R16 raw (18-bit two's complement, up to 500 samples, lead I/Q diagnostics) and R17 filtered
/// (i16, up to 100 samples). Status bytes 21-33 are kept raw; their clinical meaning is not established.
public struct ECG: Equatable {
    public let isRaw: Bool
    public let quality: UInt8, stateBits: UInt8, sampleCount: UInt16
    public let samples: [Int32]
    /// R16 only: per-sample flag bits 6 and 7, and the lead-off I/Q diagnostic halfwords.
    public let flag6: [UInt8], flag7: [UInt8], leadI: [Int16], leadQ: [Int16]
}

public struct RealtimeHR: Equatable { public let unix: UInt32, heartRate: UInt8, rrMs: [Int] }

public struct Event: Equatable {
    public let number: UInt8, unix: UInt32, payload: [UInt8]
    public var name: String { Whoop5Schema.shared.eventName(number) }
    /// BATTERY_LEVEL (3): state of charge in % (tenths on the wire) and cell voltage in mV.
    public var battery: (socPercent: Double, millivolts: Int)? {
        guard number == 3, payload.count >= 7 else { return nil }
        return (Double(payload.u16(1)) / 10, Int(payload.u16(5)))
    }
}

public struct Metadata: Equatable {
    public let type: UInt8, unix: UInt32?, subsec: UInt16?
    /// HISTORY_END only: the verbatim 8-byte token to echo in the ack, and its trim cursor.
    public let endToken: [UInt8]?
    public var trimCursor: UInt32? { endToken.map { $0.u32(0) } }
}

public struct CommandResponse: Equatable {
    public let sequence: UInt8, command: UInt8, originSequence: UInt8, result: UInt8, body: [UInt8]
    public var isPending: Bool { result == 2 }
    public var commandName: String { Whoop5Schema.shared.commandName(command) }
    /// Field-exact GET_DATA_RANGE decode on the final SUCCESS reply; nil for PENDING or a short body.
    public var dataRange: DataRange? { command == 34 && result == 1 ? DataRange(body: body) : nil }
    /// GET_CLOCK_DEPRECATED (11) reply: strap clock as Unix seconds (observed on 49 real replies).
    public var deprecatedClockUnix: UInt32? { command == 11 && result == 1 && body.count >= 4 ? body.u32(0) : nil }
}

/// GET_DATA_RANGE (34) final 65-byte body. Page cursors, not timestamps, describe the backlog.
public struct DataRange: Equatable {
    public let readPage: UInt32, writePage: UInt32, trimPage: UInt32, totalPages: UInt32
    public let newestClock: UInt32

    init?(body: [UInt8]) {
        guard body.count >= 65 else { return nil }
        readPage = body.u32(5); writePage = body.u32(9); trimPage = body.u32(13); totalPages = body.u32(21)
        newestClock = body.u32(57)
    }

    /// Ring backlog in pages: `write - trim`, wrapping through `total`. nil for an implausible frame.
    public var pagesBehind: UInt32? {
        guard totalPages > 0, writePage < totalPages, trimPage < totalPages else { return nil }
        return writePage >= trimPage ? writePage - trimPage : (totalPages - trimPage) + writePage
    }

    /// Unix seconds of the last written page; nil for the 0 / 0xFFFFFFFF sentinels.
    public var newestUnix: UInt32? { newestClock == 0 || newestClock == .max ? nil : newestClock }
}

public enum Whoop5Decoder {
    /// BLE-spec 1/1024 s ticks to ms. Not used for WHOOP 5/MG, which sends R-R in milliseconds.
    public static func rrTicksToMs(_ ticks: UInt16) -> Int { (Int(ticks) * 1000 + 512) / 1024 }

    /// Validate and decode one complete frame.
    public static func decode(_ raw: [UInt8]) throws -> Whoop5Packet {
        try Whoop5Framing.validate(raw)
        let end = raw.count - 4
        let type = raw[8]
        // Shortest body each fixed header needs; a shorter (valid-CRC) frame is kept raw, never read past.
        let minEnd: [UInt8: Int] = [36: 13, 40: 18, 48: 16, 43: 21, 47: 21]  // 50 is handled by its case guard
        if let m = minEnd[type], end < m { return .other(packetType: type, body: Array(raw[8..<end])) }
        switch type {
        case 36:
            return .commandResponse(CommandResponse(sequence: raw[9], command: raw[10], originSequence: raw[11],
                                                    result: raw[12], body: Array(raw[13..<end])))
        case 40:
            let n = Int(raw[17])
            return .realtimeHR(RealtimeHR(unix: raw.u32(10), heartRate: raw[16], rrMs: rr(raw, 18, n, 64, end)))
        case 48:
            return .event(Event(number: raw[10], unix: raw.u32(12), payload: payload(raw, end: end)))
        case 50 where end >= 21:
            // Latin-1, byte for byte, to match the Python reference on non-ASCII bytes.
            var bytes = payload(raw, end: end).dropFirst()
            while bytes.last == 0 { bytes.removeLast() }  // each fragment is NUL-terminated
            let text = String(String.UnicodeScalarView(bytes.map { Unicode.Scalar($0) }))
            return .console(sequence: raw[9], text: text)
        case 49:
            let token = raw[10] == 2 && end >= 29 ? Array(raw[21..<29]) : nil
            return .metadata(Metadata(type: raw[10], unix: end >= 15 ? raw.u32(11) : nil,
                                      subsec: end >= 17 ? raw.u16(15) : nil, endToken: token))
        case 43, 47:
            let h = RecordHeader(packetType: type, layout: raw[9], marker: raw[10], recordIndex: raw.u32(11),
                                 unix: raw.u32(15), subsec: raw.u16(19))
            return .record(h, record(raw, layout: raw[9], end: end))
        case 51, 52:
            return .imuStream(packetType: type, imuStream(raw, end: end))
        default:
            return .other(packetType: type, body: Array(raw[8..<end]))
        }
    }

    /// Event/console payload: `length` (u16 @18) bytes from offset 20, clamped to the CRC boundary.
    static func payload(_ raw: [UInt8], end: Int) -> [UInt8] {
        guard end >= 20 else { return [] }
        let n = Int(raw.u16(18))
        return Array(raw[20..<min(20 + n, end)])
    }

    static func rr(_ raw: [UInt8], _ offset: Int, _ count: Int, _ limit: Int, _ end: Int) -> [Int] {
        var out: [Int] = []
        for i in 0..<min(count, limit) {
            let o = offset + 2 * i
            guard o + 2 <= end else { break }
            let t = raw.u16(o)
            if t != 0 { out.append(Int(t)) }  // WHOOP 5/MG sends R-R in milliseconds
        }
        return out
    }

    static let expectedLength: [UInt8: Int] = [16: 1584, 17: 240, 18: 124, 20: 2140, 21: 1244, 26: 88, 22: 188]

    static func record(_ raw: [UInt8], layout: UInt8, end: Int) -> Record {
        let body = Array(raw[8..<end])
        guard let len = expectedLength[layout] else { return .unknown(body: body) }
        guard raw.count == len else { return .unexpectedLength(body: body) }
        switch layout {
        case 18:
            return .biometric(R18(
                heartRate: raw[22], rrMs: rr(raw, 24, Int(raw[23]), 4, end), hrFlags: raw[36], altHeartRate: raw[37],
                dynamicAccelG: raw.f32(41), gravityG: (raw.f32(45), raw.f32(49), raw.f32(53)),
                stepCounter: raw.u16(57), cadenceRaw: raw.u16(59), hwStepCounter: raw.u16(61), activityClass: raw[63],
                tempAux1Raw: raw.i16(69), tempAux2Raw: raw.i16(71), skinTempRaw: raw.u16(73),
                stateBits: raw[81], sleepAdjacent82: raw[82]))
        case 20:
            return .optical(R20(blocks: [26, 448, 870, 1292, 1714].map { b in
                let n = raw[b] <= 50 ? Int(raw[b]) : 0
                return OpticalBlock(
                    count: raw[b], sourceA: raw[b + 1], driveA: raw.u16(b + 2), sourceB: raw[b + 4],
                    driveB: raw.u16(b + 5), detectorA: raw[b + 7], rangeA: raw.u32(b + 8), offsetA: raw.i16(b + 12),
                    detectorB: raw[b + 14], rangeB: raw.u32(b + 15), offsetB: raw.i16(b + 19),
                    slotA: (0..<n).map { raw.i32(b + 21 + 4 * $0) }, slotB: (0..<n).map { raw.i32(b + 221 + 4 * $0) })
            }))
        case 21:
            let na = Int(raw.u16(24)), ng = Int(raw.u16(630))
            guard na <= 100, ng <= 100 else { return .unknown(body: body) }
            let col = { (o: Int, n: Int) in (0..<n).map { raw.i16(o + 2 * $0) } }
            return .imu(IMU(accel: [col(28, na), col(228, na), col(428, na)],
                            gyro: [col(640, ng), col(840, ng), col(1040, ng)]))
        case 26:
            var s: [Int64] = [Int64(raw.u32(23))]
            for i in 0..<24 { s.append(s[s.count - 1] + Int64(raw.i16(27 + 2 * i))) }
            return .compactOptical(R26(burstCounter: raw.u16(21), samples: s, motionSummary: raw.f32(75),
                                       status: raw.u16(79), onWristRaw: raw[81], acceptanceRaw: raw[82]))
        case 16, 17:
            let n = Int(raw.u16(32)), raw16 = layout == 16
            guard n <= (raw16 ? 500 : 100) else { return .unknown(body: body) }
            var samples: [Int32] = [], f6: [UInt8] = [], f7: [UInt8] = []
            var li: [Int16] = [], lq: [Int16] = []
            if raw16 {
                for i in 0..<n {
                    let o = 34 + 3 * i
                    let v = Int32(raw[o] & 0x03) << 16 | Int32(raw[o + 1]) << 8 | Int32(raw[o + 2])
                    samples.append(v >= 131_072 ? v - 262_144 : v)
                    f6.append((raw[o] >> 6) & 1); f7.append((raw[o] >> 7) & 1)
                }
                let k = min(Int(raw[1534]), 11)
                li = (0..<k).map { raw.i16(1535 + 2 * $0) }
                lq = (0..<k).map { raw.i16(1557 + 2 * $0) }
            } else {
                samples = (0..<n).map { Int32(raw.i16(34 + 2 * $0)) }
            }
            return .ecg(ECG(isRaw: raw16, quality: raw[21], stateBits: raw[22], sampleCount: UInt16(n),
                            samples: samples, flag6: f6, flag7: f7, leadI: li, leadQ: lq))
        case 22:
            let v = raw[21]
            guard v == 9 else {
                return .queuedChannel(R22(innerVersion: v, innerSubversion: raw[22], channel: nil, metadata: nil,
                                          sampleBits: []))
            }
            var bits: [Int64] = [Int64(raw.u32(31))]
            for i in 0..<49 { bits.append(bits[bits.count - 1] + Int64(raw.i16(35 + 2 * i))) }
            return .queuedChannel(R22(innerVersion: v, innerSubversion: raw[22], channel: raw[141],
                                      metadata: raw.u16(137),
                                      sampleBits: bits.map { UInt32(truncatingIfNeeded: $0) }))
        default:
            return .unknown(body: body)
        }
    }

    static func imuStream(_ raw: [UInt8], end: Int) -> IMU {
        guard end >= 28 else { return IMU(accel: [], gyro: []) }
        let na = Int(raw.u16(24)), ng = Int(raw.u16(26))
        guard 28 + 6 * na + 6 * ng <= end else { return IMU(accel: [], gyro: []) }
        var o = 28
        func col(_ n: Int) -> [Int16] { defer { o += 2 * n }; return (0..<n).map { raw.i16(o + 2 * $0) } }
        let a = [col(na), col(na), col(na)]
        let g = [col(ng), col(ng), col(ng)]
        return IMU(accel: a, gyro: g)
    }
}
