import Foundation
import StrandAnalytics
import WhoopProtocol

struct Input: Decodable {
    struct Night: Decodable { let hrv: Double?; let rhr: Double?; let resp: Double?; let sleepPerf: Double? }
    struct Cycle: Decodable { let hr: [[Double]]; let restingHR: Double?; let maxHR: Double? }
    let nights: [Night]
    let cycles: [Cycle]
}

struct Output: Encodable {
    let charge: [Double?]
    let effort: [Double?]
}

let input = try JSONDecoder().decode(Input.self, from: FileHandle.standardInput.readDataToEndOfFile())

var hrv: BaselineState?, rhr: BaselineState?, resp: BaselineState?
var charge: [Double?] = []
for night in input.nights {
    // A night is scored against the baselines of earlier nights, then folded in.
    if let h = night.hrv, let r = night.rhr, let hb = hrv {
        charge.append(RecoveryScorer.recovery(hrv: h, rhr: r, resp: night.resp, hrvBaseline: hb, rhrBaseline: rhr,
                                              respBaseline: resp, sleepPerf: night.sleepPerf.map { $0 / 100 }))
    } else {
        charge.append(nil)
    }
    hrv = Baselines.update(hrv, value: night.hrv, cfg: Baselines.hrvCfg)
    rhr = Baselines.update(rhr, value: night.rhr, cfg: Baselines.restingHRCfg)
    resp = Baselines.update(resp, value: night.resp, cfg: Baselines.respCfg)
}

let effort = input.cycles.map { cycle -> Double? in
    let samples = cycle.hr.map { HRSample(ts: Int($0[0]), bpm: Int($0[1])) }
    return StrainScorer.strain(samples, maxHR: cycle.maxHR, restingHR: cycle.restingHR ?? StrainScorer.defaultRestingHR)
}

let encoder = JSONEncoder()
FileHandle.standardOutput.write(try encoder.encode(Output(charge: charge, effort: effort)))
