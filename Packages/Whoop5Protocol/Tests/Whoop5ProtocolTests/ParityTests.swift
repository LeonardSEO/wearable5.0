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

    // Experimental metrics: same synthetic inputs and expected values as python/tests/test_experimental.py.

    static func r18(_ hr: Int, state: UInt8, skinRaw: UInt16) -> R18 {
        R18(heartRate: UInt8(hr), rrMs: [], hrFlags: 0, altHeartRate: 0, dynamicAccelG: 0, gravityG: (0, 0, 1),
            stepCounter: 0, cadenceRaw: 0, hwStepCounter: 0, activityClass: 0, tempAux1Raw: 0, tempAux2Raw: 0,
            skinTempRaw: skinRaw, stateBits: state << 4, spo2Byte82: 0)
    }

    static func header(_ unix: Int, _ index: Int, layout: UInt8) -> RecordHeader {
        RecordHeader(packetType: 47, layout: layout, marker: 0x80, recordIndex: UInt32(index), unix: UInt32(unix), subsec: 0)
    }

    /// 4000 s: wake, sleep with a 60 s awakening, 900 s wake, then a 1100 s sleep run (too short).
    static func night() -> [(RecordHeader, R18)] {
        (0..<4000).map { t in
            let asleep = (300..<2000).contains(t) && !(1000..<1060).contains(t) || (2900..<4000).contains(t)
            let state: UInt8 = asleep ? 2 : (t % 2 == 1 ? 1 : 0)
            let hr = t == 500 ? 0 : (asleep ? 48 + t % 9 : 70)
            return (header(10000 + t, t, layout: 18), r18(hr, state: state, skinRaw: UInt16(3300 + t / 100)))
        }
    }

    func testExperimentalSleepPeriods() {
        let p = Whoop5Experimental.sleepPeriods(Self.night())
        XCTAssertEqual(p.count, 1)
        guard let q = p.first else { return }
        XCTAssertEqual([Int(q.onsetUnix), Int(q.offsetUnix), q.durationS, q.asleepS, q.records, q.hrMin ?? -1],
                       [10300, 11999, 1700, 1640, 1700, 48])
        XCTAssertEqual(q.hrMean!, 52.63802236609771, accuracy: 1e-9)
        XCTAssertEqual(Whoop5Experimental.sleepPeriods([]), [])
    }

    func testExperimentalRespiratoryRate() {
        var rr = (0..<45).flatMap { _ in [950, 1000, 1050, 1000] }
        rr[20] = 250; rr[60] = 1500
        let w = Whoop5Experimental.respiratoryRate(rr)
        XCTAssertEqual(w.map { [$0.startS, $0.endS, Double($0.beats)] }, [[0, 60, 59], [60, 120, 60]])
        XCTAssertEqual(w[0].breathsPerMin!, 15.3, accuracy: 1e-9)
        XCTAssertEqual(w[1].breathsPerMin!, 15.0, accuracy: 1e-9)
        XCTAssertEqual(w[0].peakFraction!, 0.16599567526638082, accuracy: 1e-6)
        XCTAssertEqual(w[1].peakFraction!, 0.1985737846532536, accuracy: 1e-6)
        XCTAssertEqual(Whoop5Experimental.respiratoryRate([Int](repeating: 1000, count: 50)), [])
        let flat = Whoop5Experimental.respiratoryRate([Int](repeating: 1000, count: 70))
        XCTAssertEqual(flat.count, 1)
        XCTAssertNil(flat.first?.breathsPerMin)
    }

    func testExperimentalSkinTempBaseline() throws {
        let s = try XCTUnwrap(Whoop5Experimental.skinTempBaseline(Self.night()).first)
        XCTAssertEqual([Int(s.onsetUnix), Int(s.offsetUnix), s.samples], [10300, 11999, 1700])
        XCTAssertEqual(s.minC!, 33.03, accuracy: 1e-9)
        XCTAssertEqual(s.maxC!, 33.19, accuracy: 1e-9)
        XCTAssertEqual(s.meanC!, 33.11, accuracy: 1e-9)
        XCTAssertEqual(s.sdC!, 0.0489897948556632, accuracy: 1e-9)
        XCTAssertNil(s.deviationC)
        XCTAssertEqual(Whoop5Experimental.skinTempBaseline(Self.night(), baselineC: 33.0)[0].deviationC!, 0.11,
                       accuracy: 1e-9)
        let periods = [(10000, 10999), (11000, 11999)].map {
            Whoop5Experimental.SleepPeriod(onsetUnix: UInt32($0.0), offsetUnix: UInt32($0.1), durationS: 1000,
                                           asleepS: 0, records: 0, hrMin: nil, hrMean: nil)
        }
        let n = Whoop5Experimental.skinTempBaseline(Self.night(), periods: periods)
        XCTAssertEqual(n[0].meanC!, 33.045, accuracy: 1e-9)
        XCTAssertNil(n[0].deviationC)
        XCTAssertEqual(n[1].baselineC!, 33.045, accuracy: 1e-9)
        XCTAssertEqual(n[1].deviationC!, 0.1, accuracy: 1e-9)
    }

    func testExperimentalHrFromR26() {
        let x: [Int64] = (0..<(30 * 25)).map { (i: Int) -> Int64 in  // a dip every 0.8 s = 75 bpm
            let dip = i % 20 < 3 ? 800 : 0
            return Int64(100_000 + 2 * i - dip)
        }
        func rec(_ unix: Int, _ index: Int, _ counter: UInt16, _ k: Int) -> (RecordHeader, R26) {
            (Self.header(unix, index, layout: 26),
             R26(burstCounter: counter, samples: Array(x[(25 * k)..<(25 * k + 25)]), motionSummary: 0, status: 0,
                 onWristRaw: 0, acceptanceRaw: 0))
        }
        var recs = (0..<30).map { rec(5000 + $0, $0, 3, $0) }
        recs.append(recs[4])  // duplicate record_index: dropped
        recs += (0..<5).map { rec(6000 + $0, 100 + $0, 4, $0) }  // 5 s burst: too short
        let out = Whoop5Experimental.hrFromR26(recs)
        XCTAssertEqual(out.map { [Int($0.startUnix), Int($0.endUnix), $0.seconds, Int($0.burstCounter), $0.beats] },
                       [[5000, 5029, 30, 3, 37], [6000, 6004, 5, 4, 0]])
        XCTAssertEqual(out[0].heartRateBpm!, 75.0, accuracy: 1e-9)
        XCTAssertNil(out[1].heartRateBpm)
        let y: [Double] = [0, 2, 1, 3, 1, 0, 5, 4, 5, 0]  // expected values from scipy.signal.find_peaks
        XCTAssertEqual(Whoop5Experimental.findPeaks(y), [1, 3, 6, 8])
        XCTAssertEqual(Whoop5Experimental.findPeaks(y, distance: 3), [3, 8])
        XCTAssertEqual(Whoop5Experimental.findPeaks(y, prominence: 4), [6, 8])
        let one = Whoop5Experimental.bandpass((0..<250).map { sin(2 * Double.pi * Double($0) / 25) }, fs: 25,
                                              loHz: 0.6, hiHz: 3.3)
        XCTAssertGreaterThan(one[50..<200].max()!, 0.85)
        let slow = Whoop5Experimental.bandpass((0..<250).map { sin(2 * Double.pi * 0.1 * Double($0) / 25) }, fs: 25,
                                               loHz: 0.6, hiHz: 3.3)
        XCTAssertLessThan(slow[50..<200].map(abs).max()!, 0.01)
    }
}
