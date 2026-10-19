import Foundation

/// Format-1 envelope for WHOOP 5/MG: CRCs, validation, command building and BLE reassembly.
/// Pure: no CoreBluetooth. Twin of `python/whoop5/framing.py`.
public enum Whoop5Framing {
    public static let sof: UInt8 = 0xAA
    public static let format1: UInt8 = 0x01
    public static let bodyOffset = 8
    public static let minFrame = 16
    public static let maxFrame = 4096

    public static func crc16Modbus(_ data: ArraySlice<UInt8>) -> UInt16 {
        var crc: UInt16 = 0xFFFF
        for b in data {
            crc ^= UInt16(b)
            for _ in 0..<8 { crc = (crc & 1) != 0 ? (crc >> 1) ^ 0xA001 : crc >> 1 }
        }
        return crc
    }

    private static let crc32Table: [UInt32] = (0..<256).map { i -> UInt32 in
        var c = UInt32(i)
        for _ in 0..<8 { c = (c & 1) != 0 ? 0xEDB8_8320 ^ (c >> 1) : c >> 1 }
        return c
    }

    public static func crc32(_ data: ArraySlice<UInt8>) -> UInt32 {
        var c: UInt32 = 0xFFFF_FFFF
        for b in data { c = crc32Table[Int((c ^ UInt32(b)) & 0xFF)] ^ (c >> 8) }
        return c ^ 0xFFFF_FFFF
    }

    public enum FrameError: Error, Equatable {
        case tooShort, notFormat1, lengthMismatch, unaligned, headerCRC, bodyCRC
    }

    /// Throws unless `raw` is exactly one complete, CRC-valid format-1 frame.
    public static func validate(_ raw: [UInt8]) throws {
        guard raw.count >= minFrame else { throw FrameError.tooShort }
        guard raw[0] == sof, raw[1] == format1 else { throw FrameError.notFormat1 }
        let declared = Int(raw.u16(2))
        guard declared + 8 == raw.count else { throw FrameError.lengthMismatch }
        guard (declared - 4) % 4 == 0 else { throw FrameError.unaligned }
        guard crc16Modbus(raw[0..<6]) == raw.u16(6) else { throw FrameError.headerCRC }
        guard crc32(raw[bodyOffset..<(raw.count - 4)]) == raw.u32(raw.count - 4) else { throw FrameError.bodyCRC }
    }

    /// A format-1 COMMAND (type 35) frame. Builds bytes only; sending is the caller's decision.
    public static func command(_ command: UInt8, args: [UInt8] = [], sequence: UInt8 = 0,
                               destination: UInt8 = 0x00, source: UInt8 = 0x01) -> [UInt8] {
        var body: [UInt8] = [35, sequence, command] + args
        while body.count % 4 != 0 { body.append(0) }
        var header: [UInt8] = [sof, format1]
        header.appendLE(UInt16(body.count + 4))
        header += [destination, source]
        header.appendLE(crc16Modbus(header[0..<6]))
        var frame = header + body
        frame.appendLE(crc32(body[0..<body.count]))
        return frame
    }

    /// HISTORICAL_DATA_RESULT (23) for one committed chunk: `01` + the verbatim 8-byte HISTORY_END token.
    public static func historyAck(endToken: [UInt8], sequence: UInt8 = 0) -> [UInt8]? {
        guard endToken.count == 8 else { return nil }
        return command(23, args: [0x01] + endToken, sequence: sequence)
    }

    /// The fixed CLIENT_HELLO (GET_HELLO revision 1, sequence 1).
    public static var clientHello: [UInt8] { command(145, args: [0x01], sequence: 1) }
}

/// Joins BLE notification fragments into complete, CRC-valid frames. Only the first fragment of a
/// large record starts with SOF; a corrupt candidate costs one byte of resync, never a later frame.
public struct Whoop5Reassembler {
    private var buffer: [UInt8] = []

    public init() {}

    public mutating func feed(_ chunk: [UInt8]) -> [[UInt8]] {
        buffer += chunk
        var out: [[UInt8]] = []
        while true {
            guard let start = firstStart() else {
                buffer = buffer.last == Whoop5Framing.sof ? [Whoop5Framing.sof] : []
                return out
            }
            buffer.removeFirst(start)
            guard buffer.count >= 4 else { return out }
            let total = Int(buffer.u16(2)) + 8
            if total < Whoop5Framing.minFrame || total > Whoop5Framing.maxFrame {
                buffer.removeFirst()
                continue
            }
            guard buffer.count >= total else { return out }
            let candidate = Array(buffer[0..<total])
            if (try? Whoop5Framing.validate(candidate)) != nil {
                out.append(candidate)
                buffer.removeFirst(total)
            } else {
                buffer.removeFirst()
            }
        }
    }

    private func firstStart() -> Int? {
        guard buffer.count >= 2 else { return nil }
        for i in 0..<(buffer.count - 1) where buffer[i] == Whoop5Framing.sof && buffer[i + 1] == Whoop5Framing.format1 {
            return i
        }
        return nil
    }
}

extension Array where Element == UInt8 {
    func u16(_ o: Int) -> UInt16 { UInt16(self[o]) | UInt16(self[o + 1]) << 8 }
    func i16(_ o: Int) -> Int16 { Int16(bitPattern: u16(o)) }
    func u32(_ o: Int) -> UInt32 {
        UInt32(self[o]) | UInt32(self[o + 1]) << 8 | UInt32(self[o + 2]) << 16 | UInt32(self[o + 3]) << 24
    }
    func i32(_ o: Int) -> Int32 { Int32(bitPattern: u32(o)) }
    func f32(_ o: Int) -> Float { Float(bitPattern: u32(o)) }
    mutating func appendLE(_ v: UInt16) { append(UInt8(v & 0xFF)); append(UInt8(v >> 8)) }
    mutating func appendLE(_ v: UInt32) { for s in stride(from: 0, to: 32, by: 8) { append(UInt8((v >> UInt32(s)) & 0xFF)) } }
}
