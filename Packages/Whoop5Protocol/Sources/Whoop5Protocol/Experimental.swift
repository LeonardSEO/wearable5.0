import Foundation

/// Experimental metrics derived from decoded WHOOP 5/MG records. Backed by real captures (see FINDINGS)
/// but not yet checked against a clinical or WHOOP-app reference on more than one wearer.
/// Twin of `python/whoop5/experimental.py`.
public enum Whoop5Experimental {
    public struct SpO2Window: Equatable {
        public let startUnix: UInt32, endUnix: UInt32, seconds: Int, validSeconds: Int
        /// Median of the window's valid seconds (70...100 %), nil below `minValidSeconds` valid seconds.
        public let spo2Percent: Double?
    }

    /// One SpO2 value per strap measurement window: runs of R18 records with a non-zero SpO2 byte,
    /// allowing gaps of at most `maxGap` seconds. A window needs `minValidSeconds` valid seconds for a value.
    public static func spo2Windows(_ records: [(RecordHeader, R18)], maxGap: UInt32 = 2,
                                   minValidSeconds: Int = 5) -> [SpO2Window] {
        let rows = records.map { ($0.0.unix, $0.1) }.sorted { $0.0 < $1.0 }.filter { $0.1.spo2Byte82 != 0 }
        var windows: [[(UInt32, R18)]] = []
        for row in rows {
            if let last = windows.last?.last, row.0 - last.0 <= maxGap {
                windows[windows.count - 1].append(row)
            } else {
                windows.append([row])
            }
        }
        return windows.map { w in
            let valid = w.compactMap { $0.1.spo2Percent }.sorted()
            return SpO2Window(startUnix: w.first!.0, endUnix: w.last!.0, seconds: w.count, validSeconds: valid.count,
                              spo2Percent: valid.count >= max(1, minValidSeconds) ? median(valid) : nil)
        }
    }

    /// RMSSD over consecutive R-R intervals in ms, dropping intervals outside 300-2000 ms and steps of
    /// `maxStepMs` or more. Nil with fewer than 10 usable differences.
    public static func rmssdMs(_ rr: [Int], maxStepMs: Int = 200) -> Double? {
        let r = rr.filter { (300...2000).contains($0) }
        let diffs = zip(r, r.dropFirst()).map { $1 - $0 }.filter { abs($0) < maxStepMs }
        guard diffs.count >= 10 else { return nil }
        return (Double(diffs.map { $0 * $0 }.reduce(0, +)) / Double(diffs.count)).squareRoot()
    }

    static func median(_ sorted: [Int]) -> Double? {
        guard !sorted.isEmpty else { return nil }
        let m = sorted.count / 2
        return sorted.count % 2 == 1 ? Double(sorted[m]) : Double(sorted[m - 1] + sorted[m]) / 2
    }

    static func medianD(_ v: [Double]) -> Double? {
        guard !v.isEmpty else { return nil }
        let s = v.sorted(), m = s.count / 2
        return s.count % 2 == 1 ? s[m] : (s[m - 1] + s[m]) / 2
    }

    /// Neumaier-compensated sum: the algorithm Python's built-in sum() uses for floats since 3.12, so the
    /// twins agree to the last bit.
    static func fsum(_ v: [Double]) -> Double {
        var s = 0.0, c = 0.0
        for x in v {
            let t = s + x
            c += abs(s) >= abs(x) ? (s - t) + x : (x - t) + s
            s = t
        }
        return s + c
    }

    static func populationSD(_ v: [Double]) -> Double {
        let mean = fsum(v) / Double(v.count)
        return (fsum(v.map { ($0 - mean) * ($0 - mean) }) / Double(v.count)).squareRoot()
    }

    // MARK: Sleep periods

    public struct SleepPeriod: Equatable {
        public let onsetUnix: UInt32, offsetUnix: UInt32, durationS: Int, asleepS: Int, records: Int
        public let hrMin: Int?, hrMean: Double?
    }

    /// Sleep periods from the R18 band state (**experimental**). A second is asleep when bandState is SLEEP;
    /// the flag is smoothed by a majority vote over a centred `smoothS` window (by time), smoothed-asleep
    /// seconds closer than `maxGapS` form one period, and periods shorter than `minDurationS` are dropped.
    /// HR min/mean are over all records inside the period with a valid HR (25-230). The band state is the
    /// strap's motion/rest flag, not a validated sleep/wake classifier. Twin of `sleep_periods`.
    public static func sleepPeriods(_ records: [(RecordHeader, R18)], smoothS: Int = 300, maxGapS: Int = 600,
                                    minDurationS: Int = 1200) -> [SleepPeriod] {
        var seen = Set<UInt32>()
        var rows: [(t: Int, asleep: Bool, hr: Int)] = []
        for (h, r) in records.sorted(by: { $0.0.unix < $1.0.unix }) where seen.insert(h.unix).inserted {
            rows.append((Int(h.unix), r.bandState == "SLEEP", Int(r.heartRate)))
        }
        let n = rows.count, half = Double(smoothS) / 2
        var prefix = [0]
        for r in rows { prefix.append(prefix.last! + (r.asleep ? 1 : 0)) }
        var smoothed: [Bool] = [], lo = 0, hi = 0
        for r in rows {
            while Double(rows[lo].t) < Double(r.t) - half { lo += 1 }
            while hi < n && Double(rows[hi].t) <= Double(r.t) + half { hi += 1 }
            smoothed.append(2 * (prefix[hi] - prefix[lo]) > hi - lo)
        }
        var spans: [(Int, Int)] = []
        for (i, r) in rows.enumerated() where smoothed[i] {
            if let last = spans.last, r.t - last.1 <= maxGapS {
                spans[spans.count - 1].1 = r.t
            } else {
                spans.append((r.t, r.t))
            }
        }
        return spans.compactMap { start, end in
            guard end - start + 1 >= minDurationS else { return nil }
            let inside = rows.filter { start <= $0.t && $0.t <= end }
            let hrs = inside.map(\.hr).filter { (25...230).contains($0) }
            return SleepPeriod(onsetUnix: UInt32(start), offsetUnix: UInt32(end), durationS: end - start + 1,
                               asleepS: inside.filter(\.asleep).count, records: inside.count, hrMin: hrs.min(),
                               hrMean: hrs.isEmpty ? nil : Double(hrs.reduce(0, +)) / Double(hrs.count))
        }
    }

    // MARK: Respiratory rate

    public struct RespiratoryWindow: Equatable {
        public let startS: Double, endS: Double, beats: Int
        public let breathsPerMin: Double?, peakFraction: Double?
    }

    static func cleanRR(_ rr: [Int], maxStepMs: Int = 200) -> [Int] {
        var out: [Int] = [], prev: Int? = nil
        for x in rr where (300...2000).contains(x) {
            if prev == nil || abs(x - prev!) < maxStepMs { out.append(x) }
            prev = x
        }
        return out
    }

    /// Breaths per minute from respiratory sinus arrhythmia in a contiguous R-R series in ms (**experimental**).
    /// Consecutive `windowS` windows of beat time are resampled at `fs`, detrended, Hann-windowed and scanned
    /// by direct DFT from `loHz` to min(`hiHz`, half the mean beat rate) in `stepHz` steps, with power
    /// weighted by f^2 against the 1/f background. Nil rate below windowS/3 beats. Twin of `respiratory_rate`.
    public static func respiratoryRate(_ rrMs: [Int], windowS: Double = 60, fs: Double = 4, loHz: Double = 0.1,
                                       hiHz: Double = 0.5, stepHz: Double = 0.005) -> [RespiratoryWindow] {
        let rr = cleanRR(rrMs)
        var times: [Double] = [], acc = 0.0
        for x in rr { acc += Double(x) / 1000; times.append(acc) }
        var out: [RespiratoryWindow] = [], start = 0.0, i = 0
        while let lastT = times.last, start + windowS <= lastT {
            let end = start + windowS
            while i < times.count && times[i] < start { i += 1 }
            var j = i
            while j < times.count && times[j] < end { j += 1 }
            let st = Array(times[i..<j]), sv = rr[i..<j].map(Double.init)
            var rate: Double? = nil, frac: Double? = nil
            if Double(st.count) >= max(4, windowS / 3) {
                let n = Int(windowS * fs)
                var ys: [Double] = [], k = 0
                for m in 0..<n {
                    var q = start + Double(m) / fs
                    while k < st.count - 2 && st[k + 1] < q { k += 1 }
                    let t0 = st[k], t1 = st[k + 1], v0 = sv[k], v1 = sv[k + 1]
                    q = min(max(q, t0), t1)
                    ys.append(t1 > t0 ? v0 + (v1 - v0) * (q - t0) / (t1 - t0) : v0)
                }
                let mean = fsum(ys) / Double(n), xm = Double(n - 1) / 2
                let num = fsum(ys.enumerated().map { (Double($0.offset) - xm) * ($0.element - mean) })
                let den = fsum((0..<n).map { (Double($0) - xm) * (Double($0) - xm) })
                let slope = num / den
                for m in 0..<n {
                    let hann = 0.5 - 0.5 * cos(2 * Double.pi * Double(m) / Double(n - 1))
                    ys[m] = (ys[m] - mean - slope * (Double(m) - xm)) * hann
                }
                let top = min(hiHz, 0.5 * Double(st.count) / windowS)
                var bestF: Double? = nil, bestP = -1.0, total = 0.0, s = 0
                while loHz + Double(s) * stepHz <= top + 1e-9 {
                    let f = loHz + Double(s) * stepHz, w = 2 * Double.pi * f / fs
                    let re = fsum(ys.enumerated().map { $0.element * cos(w * Double($0.offset)) })
                    let im = fsum(ys.enumerated().map { $0.element * sin(w * Double($0.offset)) })
                    let p = (re * re + im * im) * f * f
                    total += p
                    if p > bestP { bestF = f; bestP = p }
                    s += 1
                }
                if let f = bestF, total > 0 { rate = f * 60; frac = bestP / total }
            }
            out.append(RespiratoryWindow(startS: start, endS: end, beats: st.count, breathsPerMin: rate,
                                         peakFraction: frac))
            start = end
        }
        return out
    }

    // MARK: Skin temperature

    public struct SkinTempNight: Equatable {
        public let onsetUnix: UInt32, offsetUnix: UInt32, samples: Int
        public let meanC: Double?, minC: Double?, maxC: Double?, sdC: Double?, baselineC: Double?, deviationC: Double?
    }

    /// Nightly skin temperature (**experimental**): mean/min/max/sd of skinTempC over each sleep period
    /// (default `sleepPeriods(records)`). deviationC = night mean minus `baselineC`, else minus the mean of the
    /// previous nights' means (nil for the first night). Uncalibrated; compare nights with each other.
    /// Twin of `skin_temp_baseline`.
    public static func skinTempBaseline(_ records: [(RecordHeader, R18)], periods: [SleepPeriod]? = nil,
                                        baselineC: Double? = nil) -> [SkinTempNight] {
        let ps = periods ?? sleepPeriods(records)
        let temps = records.compactMap { h, r in r.skinTempC.map { (h.unix, $0) } }.sorted { $0.0 < $1.0 }
        var out: [SkinTempNight] = [], means: [Double] = []
        for p in ps {
            let v = temps.filter { p.onsetUnix <= $0.0 && $0.0 <= p.offsetUnix }.map(\.1)
            guard !v.isEmpty else {
                out.append(SkinTempNight(onsetUnix: p.onsetUnix, offsetUnix: p.offsetUnix, samples: 0, meanC: nil,
                                         minC: nil, maxC: nil, sdC: nil, baselineC: nil, deviationC: nil))
                continue
            }
            let mean = fsum(v) / Double(v.count)
            let base = baselineC ?? (means.isEmpty ? nil : fsum(means) / Double(means.count))
            let sd = populationSD(v)
            out.append(SkinTempNight(onsetUnix: p.onsetUnix, offsetUnix: p.offsetUnix, samples: v.count, meanC: mean,
                                     minC: v.min(), maxC: v.max(), sdC: sd, baselineC: base,
                                     deviationC: base.map { mean - $0 }))
            means.append(mean)
        }
        return out
    }

    // MARK: HR from R26

    static func biquad(_ x: [Double], _ b: (Double, Double, Double), _ a: (Double, Double)) -> [Double] {
        var z1 = 0.0, z2 = 0.0
        return x.map { v in
            let y = b.0 * v + z1
            z1 = b.1 * v - a.0 * y + z2
            z2 = b.2 * v - a.1 * y
            return y
        }
    }

    static func butter2(_ fc: Double, _ fs: Double, high: Bool) -> ((Double, Double, Double), (Double, Double)) {
        let w0 = 2 * Double.pi * fc / fs, c = cos(w0), alpha = sin(w0) / 2.0.squareRoot(), a0 = 1 + alpha
        let b = high ? ((1 + c) / 2, -(1 + c), (1 + c) / 2) : ((1 - c) / 2, 1 - c, (1 - c) / 2)
        return ((b.0 / a0, b.1 / a0, b.2 / a0), (-2 * c / a0, (1 - alpha) / a0))
    }

    /// Zero-phase band-pass (2nd-order Butterworth high-pass + low-pass, forward and backward, odd-reflected
    /// padding of up to 2 s). Twin of `bandpass`.
    public static func bandpass(_ x: [Double], fs: Double, loHz: Double, hiHz: Double) -> [Double] {
        let n = x.count, pad = min(n - 1, Int(2 * fs))
        guard pad >= 1 else { return [Double](repeating: 0, count: n) }
        let head: [Double] = (0..<pad).map { (k: Int) -> Double in 2 * x[0] - x[pad - k] }
        let tail: [Double] = (0..<pad).map { (k: Int) -> Double in 2 * x[n - 1] - x[n - 2 - k] }
        let ext = head + x + tail
        let hp = butter2(loHz, fs, high: true), lp = butter2(hiHz, fs, high: false)
        var y = ext.map { $0 - ext[0] }
        for _ in 0..<2 { y = Array(biquad(biquad(y, hp.0, hp.1), lp.0, lp.1).reversed()) }
        return Array(y[pad..<(pad + n)])
    }

    /// Local maxima with scipy.signal.find_peaks semantics for `distance` and `prominence`. Twin of `find_peaks`.
    public static func findPeaks(_ y: [Double], distance: Int = 1, prominence: Double = 0) -> [Int] {
        guard y.count >= 3 else { return [] }
        let cand = (1..<(y.count - 1)).filter { y[$0 - 1] < y[$0] && y[$0] >= y[$0 + 1] }
        var keep = cand
        if distance > 1 {
            keep = []
            for i in cand.sorted(by: { y[$0] != y[$1] ? y[$0] > y[$1] : $0 > $1 })
            where keep.allSatisfy({ abs(i - $0) >= distance }) {
                keep.append(i)
            }
            keep.sort()
        }
        return keep.filter { p in
            var leftMin = y[p], k = p - 1
            while k >= 0 && y[k] <= y[p] { leftMin = min(leftMin, y[k]); k -= 1 }
            var rightMin = y[p]
            k = p + 1
            while k < y.count && y[k] <= y[p] { rightMin = min(rightMin, y[k]); k += 1 }
            return y[p] - max(leftMin, rightMin) >= prominence
        }
    }

    public struct R26Burst: Equatable {
        public let startUnix: UInt32, endUnix: UInt32, seconds: Int, burstCounter: UInt16, beats: Int
        public let heartRateBpm: Double?
    }

    /// Heart rate per R26 burst from the 25 Hz compact optical waveform (**experimental**): bursts are runs of
    /// consecutive seconds with one burstCounter; per burst of `minSeconds`+ s, median-removed, band-passed
    /// 0.6-3.3 Hz, inverted, peaks >= 0.33 s apart with prominence >= 0.3 sd, HR = 60 / median IBI (0.3-2.0 s,
    /// >= 5 IBIs). Tracked R18 HR at r = 0.95, MAE 1.4 bpm on 17 overnight bursts. Twin of `hr_from_r26`.
    public static func hrFromR26(_ records: [(RecordHeader, R26)], fs: Double = 25, minSeconds: Int = 12) -> [R26Burst] {
        var seen = Set<UInt32>()
        let rows = records.filter { !$0.1.samples.isEmpty }
            .sorted { ($0.0.unix, $0.0.recordIndex) < ($1.0.unix, $1.0.recordIndex) }
            .filter { seen.insert($0.0.recordIndex).inserted }
        var bursts: [[(RecordHeader, R26)]] = []
        for r in rows {
            if let last = bursts.last?.last, r.0.unix == last.0.unix + 1, r.1.burstCounter == last.1.burstCounter {
                bursts[bursts.count - 1].append(r)
            } else {
                bursts.append([r])
            }
        }
        return bursts.map { (b: [(RecordHeader, R26)]) -> R26Burst in
            let x: [Double] = b.flatMap { (r: (RecordHeader, R26)) -> [Double] in r.1.samples.map { Double($0) } }
            var beats = 0, hr: Double? = nil
            if Double(x.count) >= fs * Double(minSeconds), let med = medianD(x) {
                let y = bandpass(x.map { $0 - med }, fs: fs, loHz: 0.6, hiHz: 3.3).map { -$0 }
                let sd = populationSD(y)
                let peaks = findPeaks(y, distance: Int(fs * 0.33), prominence: 0.3 * sd)
                var ibi: [Double] = []
                for (p, q) in zip(peaks, peaks.dropFirst()) {
                    let v = Double(q - p) / fs
                    if v > 0.3 && v < 2.0 { ibi.append(v) }
                }
                beats = peaks.count
                if ibi.count >= 5, let m = medianD(ibi) { hr = 60 / m }
            }
            return R26Burst(startUnix: b[0].0.unix, endUnix: b[b.count - 1].0.unix, seconds: b.count,
                            burstCounter: b[0].1.burstCounter, beats: beats, heartRateBpm: hr)
        }
    }
}
