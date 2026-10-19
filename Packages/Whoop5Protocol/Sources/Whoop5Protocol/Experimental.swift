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
}
