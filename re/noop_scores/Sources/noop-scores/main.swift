import Foundation
import StrandAnalytics
import WhoopProtocol

// Runs NOOP's own scorers on caller-supplied nights, cycles and workouts. Nothing of NOOP is copied here.
struct Input: Decodable {
    struct Night: Decodable {
        let hrv: Double?; let rhr: Double?; let resp: Double?; let sleepPerf: Double?; let skinTemp: Double?
        // Optional sleep totals for NOOP's Rest composite and its sleep-need ledger (seconds; consistency 0-1).
        let tst: Double?; let inBed: Double?; let efficiency: Double?; let restorative: Double?; let deep: Double?
        let consistency: Double?
        let creditedSleepMin: Double?   // main sleep + naps; nil = a day with no usable sleep (skipped, as NOOP does)
    }
    struct Cycle: Decodable { let hr: [[Double]]; let restingHR: Double?; let maxHR: Double? }
    struct Workout: Decodable { let hr: [[Double]]; let maxHR: Double }
    let nights: [Night]
    let cycles: [Cycle]
    let workouts: [Workout]?
}

struct Output: Encodable {
    let charge: [Double?]          // Charge with the caller's sleepPerf (WHOOP's sleep performance stands in for Rest)
    let chargeOwnRest: [Double?]   // Charge with NOOP's own Rest composite: the app's real path
    let rest: [Double?]
    let needHours: [Double]        // personalized need from earlier nights only (age unknown: 8 h floor)
    let needMin: [Double?]         // need for the night = needHours * 60 + ledger debt from earlier nights
    let effort: [Double?]
    let zones: [[Double]]          // seconds below zone 1, then zones 1-5
}

let input = try JSONDecoder().decode(Input.self, from: FileHandle.standardInput.readDataToEndOfFile())

var rest: [Double?] = [], needHours: [Double] = [], needMin: [Double?] = []
var priorHours: [Double] = [], priorSeries: [(day: String, totalSleepMin: Double?)] = []
for (i, n) in input.nights.enumerated() {
    let need = AnalyticsEngine.Rest.personalizedNeedHours(nightlyHours: priorHours, age: nil)
    needHours.append(need)
    let ledger = SleepDebt.ledger(series: priorSeries, needHours: need)
    needMin.append(n.creditedSleepMin == nil ? nil : need * 60 + (ledger.isDebt ? ledger.magnitudeMin : 0))
    if let tst = n.tst, tst > 0, let inBed = n.inBed, let eff = n.efficiency, let restor = n.restorative {
        rest.append(AnalyticsEngine.Rest.composite(tstSeconds: tst, inBedSeconds: inBed, efficiency: eff,
                                                   restorativeSeconds: restor, needHours: need,
                                                   consistency: n.consistency, deepSeconds: n.deep))
    } else { rest.append(nil) }
    if let m = n.creditedSleepMin, m > 0 { priorHours.append(m / 60) }
    priorSeries.append((day: String(i), totalSleepMin: n.creditedSleepMin))
}

func charges(_ sleepPerf: (Int) -> Double?) -> [Double?] {
    var hrv: BaselineState?, rhr: BaselineState?, resp: BaselineState?, skin: BaselineState?
    var out: [Double?] = []
    for (i, night) in input.nights.enumerated() {
        // A night is scored against the baselines of earlier nights, then folded in.
        if let h = night.hrv, let r = night.rhr, let hb = hrv {
            // Skin-temperature deviation as AnalyticsEngine computes it: only against a usable baseline.
            let skinDev = night.skinTemp.flatMap { v in skin.flatMap { $0.usable ? (Baselines.deviation(v, state: $0).delta * 100).rounded() / 100 : nil } }
            out.append(RecoveryScorer.recovery(hrv: h, rhr: r, resp: night.resp, hrvBaseline: hb, rhrBaseline: rhr,
                                               respBaseline: resp, sleepPerf: sleepPerf(i).map { $0 / 100 },
                                               skinTempDev: skinDev))
        } else {
            out.append(nil)
        }
        hrv = Baselines.update(hrv, value: night.hrv, cfg: Baselines.hrvCfg)
        rhr = Baselines.update(rhr, value: night.rhr, cfg: Baselines.restingHRCfg)
        resp = Baselines.update(resp, value: night.resp, cfg: Baselines.respCfg)
        skin = Baselines.update(skin, value: night.skinTemp, cfg: Baselines.metricCfg["skin_temp"]!)
    }
    return out
}

let effort = input.cycles.map { cycle -> Double? in
    let samples = cycle.hr.map { HRSample(ts: Int($0[0]), bpm: Int($0[1])) }
    return StrainScorer.strain(samples, maxHR: cycle.maxHR, restingHR: cycle.restingHR ?? StrainScorer.defaultRestingHR)
}

let zones = (input.workouts ?? []).map { w -> [Double] in
    let t = HRZones.timeInZone(w.hr.map { HRSample(ts: Int($0[0]), bpm: Int($0[1])) }, zoneSet: HRZones.zones(maxHR: w.maxHR))
    return [t.belowZone1] + (1...5).map { t.seconds(inZone: $0) }
}

FileHandle.standardOutput.write(try JSONEncoder().encode(Output(
    charge: charges { input.nights[$0].sleepPerf }, chargeOwnRest: charges { rest[$0] }, rest: rest,
    needHours: needHours, needMin: needMin, effort: effort, zones: zones)))
