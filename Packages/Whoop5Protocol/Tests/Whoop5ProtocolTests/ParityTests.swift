import XCTest
@testable import Whoop5Protocol

/// Decodes every vector in golden.json (written by `python/gen_golden.py`) and compares against the
/// Python reference decode. A mismatch means the two implementations drifted.
final class ParityTests: XCTestCase {
    struct Vector: Decodable {
        let name: String
        let hex: String
        let expected: [String: AnyJSON]
    }

    enum AnyJSON: Decodable, Equatable {
        case int(Int), double(Double), string(String), array([AnyJSON]), null
        init(from d: Decoder) throws {
            let c = try d.singleValueContainer()
            if c.decodeNil() { self = .null }
            else if let i = try? c.decode(Int.self) { self = .int(i) }
            else if let x = try? c.decode(Double.self) { self = .double(x) }
            else if let s = try? c.decode(String.self) { self = .string(s) }
            else { self = .array(try c.decode([AnyJSON].self)) }
        }
        var int: Int? { if case .int(let i) = self { return i }; return nil }
        var double: Double? {
            switch self { case .double(let x): return x; case .int(let i): return Double(i); default: return nil }
        }
        var ints: [Int]? { if case .array(let a) = self { return a.compactMap(\.int) }; return nil }
    }

    func vectors() throws -> [Vector] {
        let url = try XCTUnwrap(Bundle.module.url(forResource: "golden", withExtension: "json"))
        return try JSONDecoder().decode([Vector].self, from: Data(contentsOf: url))
    }

    func bytes(_ hex: String) -> [UInt8] {
        var out: [UInt8] = []
        var i = hex.startIndex
        while i < hex.endIndex {
            let j = hex.index(i, offsetBy: 2)
            out.append(UInt8(hex[i..<j], radix: 16)!)
            i = j
        }
        return out
    }

    func testGoldenParity() throws {
        let vs = try vectors()
        XCTAssertGreaterThanOrEqual(vs.count, 18)
        for v in vs {
            let e = v.expected
            let packet = try Whoop5Decoder.decode(bytes(v.hex))
            switch packet {
            case .record(let h, let rec):
                XCTAssertEqual(Int(h.layout), e["layout"]?.int, v.name)
                XCTAssertEqual(Int(h.unix), e["unix_s"]?.int, v.name)
                XCTAssertEqual(Int(h.recordIndex), e["record_index"]?.int, v.name)
                switch rec {
                case .biometric(let r):
                    XCTAssertEqual(Int(r.heartRate), e["heart_rate"]?.int, v.name)
                    XCTAssertEqual(r.rrMs, e["rr_ms"]?.ints, v.name)
                    XCTAssertEqual(Int(r.stepCounter), e["step_counter"]?.int, v.name)
                    XCTAssertEqual(r.skinTempC, e["skin_temp_c"]?.double, v.name)
                    XCTAssertEqual(r.tempAux1C, e["temp_aux1_c"]?.double, v.name)
                    if case .string(let s) = e["band_state"] { XCTAssertEqual(r.bandState, s, v.name) }
                    XCTAssertEqual(r.spo2Percent, e["spo2_percent"]?.int, v.name)
                case .imu(let imu):
                    XCTAssertEqual(imu.accel[0].map(Int.init), e["accel_x"]?.ints, v.name)
                    XCTAssertEqual(imu.gyro[2].map(Int.init), e["gyro_z"]?.ints, v.name)
                case .compactOptical(let r):
                    XCTAssertEqual(r.samples.map { Int($0) }, e["samples"]?.ints, v.name)
                    XCTAssertEqual(Int(r.burstCounter), e["burst_counter"]?.int, v.name)
                case .ecg(let r):
                    XCTAssertEqual(Int(r.sampleCount), e["sample_count"]?.int, v.name)
                    XCTAssertEqual(Int(r.quality), e["quality"]?.int, v.name)
                    XCTAssertEqual(r.samples.map { Int($0) }, e["samples"]?.ints, v.name)
                    if r.isRaw { XCTAssertEqual(r.leadI.map { Int($0) }, e["lead_i"]?.ints, v.name) }
                default:
                    XCTFail("unexpected record for \(v.name)")
                }
            case .realtimeHR(let r):
                XCTAssertEqual(Int(r.heartRate), e["heart_rate"]?.int, v.name)
                XCTAssertEqual(r.rrMs, e["rr_ms"]?.ints, v.name)
            case .commandResponse(let c):
                XCTAssertEqual(Int(c.command), e["command"]?.int, v.name)
                let dr = try XCTUnwrap(c.dataRange)
                XCTAssertEqual(dr.pagesBehind.map(Int.init), e["pages_behind"]?.int, v.name)
                XCTAssertEqual(dr.newestUnix.map(Int.init), e["newest_unix"]?.int, v.name)
            case .console(let seq, let text):
                XCTAssertEqual(Int(seq), e["console_sequence"]?.int, v.name)
                if case .string(let t) = e["text"] { XCTAssertEqual(text, t, v.name) }
            case .event(let ev):
                XCTAssertEqual(Int(ev.number), e["event"]?.int, v.name)
                if let b = ev.battery {
                    XCTAssertEqual(b.socPercent, e["soc_percent"]?.double, v.name)
                    XCTAssertEqual(b.millivolts, e["millivolts"]?.int, v.name)
                }
                if case .string(let s) = e["event_name"] { XCTAssertEqual(ev.name, s, v.name) }
            case .metadata(let m):
                XCTAssertEqual(Int(m.type), e["meta_type"]?.int, v.name)
                XCTAssertEqual(m.trimCursor.map(Int.init), e["trim_cursor"]?.int, v.name)
                XCTAssertEqual(m.unix.map(Int.init), e["unix_s"]?.int, v.name)
            default:
                XCTFail("unexpected packet for \(v.name)")
            }
        }
    }

    func testClientHelloAndHistoryAckAreByteExact() {
        XCTAssertEqual(Whoop5Framing.clientHello, bytes("aa0108000001e67123019101363e5c8d"))
        XCTAssertEqual(Whoop5Framing.historyAck(endToken: bytes("41b6010010000000")),
                       bytes("aa0110000001e0d12300170141b6010010000000667da4fb"))
    }

    func testReassemblerAcrossFragments() throws {
        let frames = try vectors().map { bytes($0.hex) }
        let stream: [UInt8] = [0x00, 0x13] + Array(frames.joined())
        var r = Whoop5Reassembler()
        var out: [[UInt8]] = []
        var i = 0
        while i < stream.count {
            out += r.feed(Array(stream[i..<min(i + 244, stream.count)]))
            i += 244
        }
        XCTAssertEqual(out, frames)
    }

    func testCorruptFrameRejected() throws {
        var f = bytes(try vectors()[0].hex)
        f[30] ^= 1
        XCTAssertThrowsError(try Whoop5Decoder.decode(f))
    }

    func testSchemaNames() {
        XCTAssertEqual(Whoop5Schema.shared.commandName(34), "GET_DATA_RANGE")
        XCTAssertEqual(Whoop5Schema.shared.eventName(9), "WRIST_ON")
        XCTAssertTrue(Whoop5Schema.shared.destructiveCommands.contains(29))
    }

    func testExperimentalSpO2WindowsAndRmssd() throws {
        func r18(_ unix: UInt32, _ b82: UInt8) throws -> (RecordHeader, R18) {
            var body = [UInt8](repeating: 0, count: 112)
            body[0] = 47; body[1] = 18; body[2] = 0x80
            for k in 0..<4 { body[7 + k] = UInt8((unix >> (8 * UInt32(k))) & 0xFF) }
            body[22 - 8] = 55; body[82 - 8] = b82
            var header: [UInt8] = [0xAA, 0x01]; header.appendLE(UInt16(body.count + 4)); header += [0x01, 0x00]
            header.appendLE(Whoop5Framing.crc16Modbus(header[0..<6]))
            var frame = header + body; frame.appendLE(Whoop5Framing.crc32(body[0..<body.count]))
            guard case .record(let h, .biometric(let r)) = try Whoop5Decoder.decode(frame) else {
                XCTFail("not R18"); throw CocoaError(.coderInvalidValue)
            }
            return (h, r)
        }
        let seq: [(UInt32, UInt8)] = [(100, 0), (101, 128), (102, 97), (103, 96), (104, 160), (105, 98), (106, 0),
                                      (2000, 32), (2001, 160)]
        let w = Whoop5Experimental.spo2Windows(try seq.map { try r18($0.0, $0.1) }, minValidSeconds: 1)
        XCTAssertEqual(w.map { [Int($0.startUnix), Int($0.endUnix), $0.seconds, $0.validSeconds] },
                       [[101, 105, 5, 3], [2000, 2001, 2, 0]])
        XCTAssertEqual(w.map { $0.spo2Percent }, [97.0, nil])
        let rr = [1000, 1010, 990, 1000, 1020, 1000, 990, 1010, 1000, 990, 1000, 1500]
        XCTAssertEqual(Whoop5Experimental.rmssdMs(rr)!, 14.8323970, accuracy: 1e-5)
        XCTAssertNil(Whoop5Experimental.rmssdMs([1000, 1010]))
    }
}
