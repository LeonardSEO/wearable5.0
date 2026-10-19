import Foundation
import Whoop5Protocol

// whoop5-decode <hex>...            decode frames given as hex
// whoop5-decode --parity golden.json  check the Swift decoder against the Python reference vectors
//                                      (runs without XCTest, e.g. with Command Line Tools only)

func bytes(_ hex: String) -> [UInt8]? {
    let h = Array(hex.utf8)
    guard h.count % 2 == 0 else { return nil }
    var out: [UInt8] = []
    var i = 0
    while i < h.count {
        guard let b = UInt8(String(decoding: h[i..<i + 2], as: UTF8.self), radix: 16) else { return nil }
        out.append(b)
        i += 2
    }
    return out
}

func summary(_ p: Whoop5Packet) -> [String: Any] {
    switch p {
    case .record(let h, let r):
        var d: [String: Any] = ["layout": Int(h.layout), "unix_s": Int(h.unix), "record_index": Int(h.recordIndex)]
        switch r {
        case .biometric(let x):
            d["heart_rate"] = Int(x.heartRate); d["rr_ms"] = x.rrMs; d["step_counter"] = Int(x.stepCounter)
            d["skin_temp_c"] = x.skinTempC as Any; d["temp_aux1_c"] = x.tempAux1C as Any; d["band_state"] = x.bandState
        case .imu(let x): d["accel_x"] = x.accel[0].map(Int.init); d["gyro_z"] = x.gyro[2].map(Int.init)
        case .compactOptical(let x): d["samples"] = x.samples.map { Int($0) }; d["burst_counter"] = Int(x.burstCounter)
        case .optical(let x): d["blocks"] = x.blocks.map { Int($0.count) }
        case .queuedChannel(let x): d["inner_version"] = Int(x.innerVersion)
        case .unknown, .unexpectedLength: d["record"] = "raw"
        }
        return d
    case .realtimeHR(let x): return ["heart_rate": Int(x.heartRate), "rr_ms": x.rrMs, "unix_s": Int(x.unix)]
    case .commandResponse(let c):
        var d: [String: Any] = ["command": Int(c.command), "command_name": c.commandName, "result": Int(c.result)]
        if let r = c.dataRange { d["pages_behind"] = r.pagesBehind.map { Int($0) } as Any; d["newest_unix"] = r.newestUnix.map { Int($0) } as Any }
        return d
    case .event(let e): return ["event": Int(e.number), "event_name": e.name, "unix_s": Int(e.unix)]
    case .metadata(let m):
        return ["meta_type": Int(m.type), "trim_cursor": m.trimCursor.map { Int($0) } as Any, "unix_s": m.unix.map { Int($0) } as Any]
    case .imuStream(let t, let x): return ["packet_type": Int(t), "accel_count": x.accelCount]
    case .other(let t, _): return ["packet_type": Int(t)]
    }
}

func same(_ a: Any?, _ b: Any?) -> Bool {
    let na = (a as? NSObject).flatMap { $0 is NSNull ? nil : $0 }, nb = (b as? NSObject).flatMap { $0 is NSNull ? nil : $0 }
    if na == nil || nb == nil { return na == nil && nb == nil }
    if let x = na as? NSNumber, let y = nb as? NSNumber { return abs(x.doubleValue - y.doubleValue) < 1e-9 }
    return na!.isEqual(nb!)
}

let args = Array(CommandLine.arguments.dropFirst())
if args.first == "--parity", args.count == 2 {
    let data = try Data(contentsOf: URL(fileURLWithPath: args[1]))
    let vectors = try JSONSerialization.jsonObject(with: data) as! [[String: Any]]
    var failures = 0, checks = 0
    for v in vectors {
        let name = v["name"] as! String
        guard let raw = bytes(v["hex"] as! String), let p = try? Whoop5Decoder.decode(raw) else {
            print("FAIL \(name): did not decode"); failures += 1; continue
        }
        let got = summary(p)
        for (k, exp) in v["expected"] as! [String: Any] where !["packet_type"].contains(k) {
            guard got.keys.contains(k) else { continue }
            checks += 1
            if !same(got[k], exp) { print("FAIL \(name).\(k): swift=\(got[k] ?? "nil") python=\(exp)"); failures += 1 }
        }
    }
    print("\(vectors.count) vectors, \(checks) field checks, \(failures) failures")
    exit(failures == 0 ? 0 : 1)
}

for hex in args {
    guard let raw = bytes(hex) else { print("not hex: \(hex)"); continue }
    do { print(summary(try Whoop5Decoder.decode(raw))) } catch { print("invalid frame: \(error)") }
}
