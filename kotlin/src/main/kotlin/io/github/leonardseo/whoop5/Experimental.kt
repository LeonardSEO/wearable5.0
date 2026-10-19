package io.github.leonardseo.whoop5

import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.sin
import kotlin.math.sqrt

/**
 * Experimental metrics derived from decoded WHOOP 5/MG records. Backed by real captures (see FINDINGS) but
 * not yet checked against a clinical or WHOOP-app reference on more than one wearer.
 * Twin of `python/whoop5/experimental.py` and the Swift `Whoop5Experimental`.
 */
object Whoop5Experimental {
    data class SpO2Window(val startUnix: Long, val endUnix: Long, val seconds: Int, val validSeconds: Int,
                          /** Median of the window's valid seconds (70..100 %), null below `minValidSeconds`. */
                          val spo2Percent: Double?)

    /**
     * One SpO2 value per strap measurement window: runs of R18 records with a non-zero SpO2 byte, allowing
     * gaps of at most [maxGap] seconds. A window needs [minValidSeconds] valid seconds for a value.
     */
    fun spo2Windows(records: List<Pair<RecordHeader, R18>>, maxGap: Long = 2, minValidSeconds: Int = 5): List<SpO2Window> {
        val rows = records.map { it.first.unix to it.second }.sortedBy { it.first }.filter { it.second.spo2Byte82 != 0 }
        val windows = mutableListOf<MutableList<Pair<Long, R18>>>()
        for (row in rows) {
            val last = windows.lastOrNull()?.lastOrNull()
            if (last != null && row.first - last.first <= maxGap) windows.last().add(row) else windows.add(mutableListOf(row))
        }
        return windows.map { w ->
            val valid = w.mapNotNull { it.second.spo2Percent }.sorted()
            SpO2Window(w.first().first, w.last().first, w.size, valid.size,
                if (valid.size >= maxOf(1, minValidSeconds)) median(valid) else null)
        }
    }

    /**
     * RMSSD over consecutive R-R intervals in ms, dropping intervals outside 300-2000 ms and steps of
     * [maxStepMs] or more. null with fewer than 10 usable differences.
     */
    fun rmssdMs(rr: List<Int>, maxStepMs: Int = 200): Double? {
        val r = rr.filter { it in 300..2000 }
        val diffs = r.zipWithNext { a, b -> b - a }.filter { abs(it) < maxStepMs }
        if (diffs.size < 10) return null
        return sqrt(diffs.sumOf { (it * it).toLong() }.toDouble() / diffs.size)
    }

    private fun median(sorted: List<Int>): Double? {
        if (sorted.isEmpty()) return null
        val m = sorted.size / 2
        return if (sorted.size % 2 == 1) sorted[m].toDouble() else (sorted[m - 1] + sorted[m]) / 2.0
    }

    // ---- sleep periods -------------------------------------------------------------------------------

    data class SleepPeriod(val onsetUnix: Long, val offsetUnix: Long, val durationS: Int, val asleepS: Int,
                           val records: Int, val hrMin: Int?, val hrMean: Double?)

    private fun validHr(hr: Int?): Boolean = hr != null && hr in 25..230

    /**
     * Sleep periods from the R18 band state (**experimental**). A second counts as asleep when the band state
     * is SLEEP; the flag is smoothed by a majority vote over a centred [smoothS] window (by time), smoothed
     * asleep seconds closer than [maxGapS] form one period, and periods shorter than [minDurationS] are
     * dropped. HR min/mean use records with a valid HR (25-230). Band state is the strap's motion/rest flag,
     * not a sleep stage. Twin of `sleep_periods`.
     */
    fun sleepPeriods(records: List<Pair<RecordHeader, R18>>, smoothS: Int = 300, maxGapS: Int = 600,
                     minDurationS: Int = 1200): List<SleepPeriod> {
        val seen = HashSet<Long>()
        val rows = records.sortedBy { it.first.unix }.filter { seen.add(it.first.unix) }
            .map { Triple(it.first.unix, it.second.bandState == "SLEEP", it.second.heartRate) }
        val n = rows.size
        val half = smoothS / 2.0
        val prefix = IntArray(n + 1)
        for (k in 0 until n) prefix[k + 1] = prefix[k] + if (rows[k].second) 1 else 0
        val smoothed = BooleanArray(n)
        var lo = 0; var hi = 0
        for (k in 0 until n) {
            val t = rows[k].first
            while (rows[lo].first < t - half) lo++
            while (hi < n && rows[hi].first <= t + half) hi++
            smoothed[k] = 2 * (prefix[hi] - prefix[lo]) > hi - lo
        }
        val spans = mutableListOf<LongArray>()
        for (k in 0 until n) {
            if (!smoothed[k]) continue
            val t = rows[k].first
            if (spans.isNotEmpty() && t - spans.last()[1] <= maxGapS) spans.last()[1] = t else spans.add(longArrayOf(t, t))
        }
        return spans.filter { it[1] - it[0] + 1 >= minDurationS }.map { (start, end) ->
            val inside = rows.filter { it.first in start..end }
            val hrs = inside.map { it.third }.filter { validHr(it) }
            SleepPeriod(start, end, (end - start + 1).toInt(), inside.count { it.second }, inside.size,
                hrs.minOrNull(), if (hrs.isEmpty()) null else sumSeq(hrs.map { it.toDouble() }) / hrs.size)
        }
    }

    // ---- respiratory rate ------------------------------------------------------------------------------

    data class RespiratoryWindow(val startS: Double, val endS: Double, val beats: Int, val breathsPerMin: Double?,
                                 val peakFraction: Double?)

    private fun cleanRr(rr: List<Int>, maxStepMs: Int = 200): List<Int> {
        val out = mutableListOf<Int>(); var prev: Int? = null
        for (x in rr) {
            if (x !in 300..2000) continue
            if (prev == null || abs(x - prev) < maxStepMs) out.add(x)
            prev = x
        }
        return out
    }

    /**
     * Breaths per minute from respiratory sinus arrhythmia in an R-R series (**experimental**): consecutive
     * [windowS] windows of beat time, tachogram resampled at [fs], detrended, Hann-windowed, f²-weighted DFT
     * power from [loHz] to min([hiHz], half the beat rate) in [stepHz] steps. Twin of `respiratory_rate`.
     */
    fun respiratoryRate(rrMs: List<Int>, windowS: Double = 60.0, fs: Double = 4.0, loHz: Double = 0.1,
                        hiHz: Double = 0.5, stepHz: Double = 0.005): List<RespiratoryWindow> {
        val rr = cleanRr(rrMs)
        val times = ArrayList<Double>(rr.size); var acc = 0.0
        for (x in rr) { acc += x / 1000.0; times.add(acc) }
        val out = mutableListOf<RespiratoryWindow>()
        var start = 0.0; var i = 0
        while (times.isNotEmpty() && start + windowS <= times.last()) {
            val end = start + windowS
            while (i < times.size && times[i] < start) i++
            var j = i
            while (j < times.size && times[j] < end) j++
            val selT = times.subList(i, j); val selV = rr.subList(i, j)
            var bpm: Double? = null; var frac: Double? = null
            if (selT.size >= maxOf(4.0, windowS / 3)) {
                val n = (windowS * fs).toInt()
                val ys = DoubleArray(n); var k = 0
                for (m in 0 until n) {
                    var q = start + m / fs
                    while (k < selT.size - 2 && selT[k + 1] < q) k++
                    val t0 = selT[k]; val t1 = selT[k + 1]; val v0 = selV[k].toDouble(); val v1 = selV[k + 1].toDouble()
                    q = minOf(maxOf(q, t0), t1)
                    ys[m] = if (t1 > t0) v0 + (v1 - v0) * (q - t0) / (t1 - t0) else v0
                }
                val mean = sumSeq(ys.toList()) / n; val xm = (n - 1) / 2.0
                val num = sumSeq(List(n) { m -> (m - xm) * (ys[m] - mean) })
                val den = sumSeq(List(n) { m -> (m - xm) * (m - xm) })
                val slope = num / den
                for (m in 0 until n) ys[m] = (ys[m] - mean - slope * (m - xm)) * (0.5 - 0.5 * cos(2 * PI * m / (n - 1)))
                val top = minOf(hiHz, 0.5 * selT.size / windowS)
                var bestF: Double? = null; var bestP = -1.0; var total = 0.0; var s = 0
                while (loHz + s * stepHz <= top + 1e-9) {
                    val f = loHz + s * stepHz
                    val w = 2 * PI * f / fs
                    val re = sumSeq(List(n) { m -> ys[m] * cos(w * m) })
                    val im = sumSeq(List(n) { m -> ys[m] * sin(w * m) })
                    val p = (re * re + im * im) * f * f
                    total += p
                    if (p > bestP) { bestF = f; bestP = p }
                    s++
                }
                if (bestF != null && total > 0) { bpm = bestF * 60; frac = bestP / total }
            }
            out.add(RespiratoryWindow(start, end, selT.size, bpm, frac))
            start = end
        }
        return out
    }

    // ---- skin temperature ------------------------------------------------------------------------------

    data class SkinTempNight(val onsetUnix: Long, val offsetUnix: Long, val samples: Int, val meanC: Double?,
                             val minC: Double?, val maxC: Double?, val sdC: Double?, val baselineC: Double?,
                             val deviationC: Double?)

    /**
     * Nightly skin temperature (**experimental**): mean/min/max/sd of R18 skin temperature over each sleep
     * period ([periods] default to [sleepPeriods]); deviation from [baselineC] or from the mean of previous
     * nights. Uncalibrated wrist sensor: compare nights with each other. Twin of `skin_temp_baseline`.
     */
    fun skinTempBaseline(records: List<Pair<RecordHeader, R18>>, periods: List<SleepPeriod>? = null,
                         baselineC: Double? = null): List<SkinTempNight> {
        val ps = periods ?: sleepPeriods(records)
        val temps = records.mapNotNull { r -> r.second.skinTempC?.let { r.first.unix to it } }
            .sortedWith(compareBy({ it.first }, { it.second }))
        val means = mutableListOf<Double>()
        return ps.map { p ->
            val v = temps.filter { it.first in p.onsetUnix..p.offsetUnix }.map { it.second }
            if (v.isEmpty()) SkinTempNight(p.onsetUnix, p.offsetUnix, 0, null, null, null, null, null, null)
            else {
                val mean = sumSeq(v) / v.size
                val base = baselineC ?: if (means.isEmpty()) null else sumSeq(means) / means.size
                val sd = sqrt(sumSeq(v.map { (it - mean) * (it - mean) }) / v.size)
                means.add(mean)
                SkinTempNight(p.onsetUnix, p.offsetUnix, v.size, mean, v.minOrNull(), v.maxOrNull(), sd, base,
                    base?.let { mean - it })
            }
        }
    }

    // ---- optical heart rate (R26) ----------------------------------------------------------------------

    data class R26Burst(val startUnix: Long, val endUnix: Long, val seconds: Int, val burstCounter: Int, val beats: Int,
                        val heartRateBpm: Double?)

    private fun biquad(x: DoubleArray, b: DoubleArray, a: DoubleArray): DoubleArray {
        var z1 = 0.0; var z2 = 0.0
        return DoubleArray(x.size) { k ->
            val v = x[k]; val y = b[0] * v + z1
            z1 = b[1] * v - a[0] * y + z2
            z2 = b[2] * v - a[1] * y
            y
        }
    }

    private fun butter2(fc: Double, fs: Double, high: Boolean): Pair<DoubleArray, DoubleArray> {
        val w0 = 2 * PI * fc / fs
        val c = cos(w0); val alpha = sin(w0) / sqrt(2.0); val a0 = 1 + alpha
        val b = if (high) doubleArrayOf((1 + c) / 2, -(1 + c), (1 + c) / 2) else doubleArrayOf((1 - c) / 2, 1 - c, (1 - c) / 2)
        return Pair(doubleArrayOf(b[0] / a0, b[1] / a0, b[2] / a0), doubleArrayOf(-2 * c / a0, (1 - alpha) / a0))
    }

    /** Zero-phase band-pass (2nd-order Butterworth HP + LP, forward and backward, odd-reflected padding). */
    fun bandpass(x: List<Double>, fs: Double, loHz: Double, hiHz: Double): List<Double> {
        val n = x.size
        val pad = minOf(n - 1, (2 * fs).toInt())
        if (pad < 1) return List(n) { 0.0 }
        val ext = ArrayList<Double>(n + 2 * pad)
        for (k in pad downTo 1) ext.add(2 * x[0] - x[k])
        ext.addAll(x)
        for (k in 0 until pad) ext.add(2 * x[n - 1] - x[n - 2 - k])
        val (hb, ha) = butter2(loHz, fs, true); val (lb, la) = butter2(hiHz, fs, false)
        var y = DoubleArray(ext.size) { ext[it] - ext[0] }
        repeat(2) { y = biquad(biquad(y, hb, ha), lb, la).reversedArray() }
        return y.toList().subList(pad, pad + n)
    }

    /** Local maxima with scipy.signal.find_peaks semantics for [distance] and [prominence]. */
    fun findPeaks(y: List<Double>, distance: Int = 1, prominence: Double = 0.0): List<Int> {
        val cand = (1 until y.size - 1).filter { y[it - 1] < y[it] && y[it] >= y[it + 1] }
        var keep: Set<Int> = cand.toSet()
        if (distance > 1) {
            val kept = mutableSetOf<Int>()
            for (i in cand.sortedWith(compareBy({ -y[it] }, { -it }))) if (kept.all { abs(i - it) >= distance }) kept.add(i)
            keep = kept
        }
        return keep.sorted().filter { p ->
            var leftMin = y[p]; var k = p - 1
            while (k >= 0 && y[k] <= y[p]) { leftMin = minOf(leftMin, y[k]); k-- }
            var rightMin = y[p]; k = p + 1
            while (k < y.size && y[k] <= y[p]) { rightMin = minOf(rightMin, y[k]); k++ }
            y[p] - maxOf(leftMin, rightMin) >= prominence
        }
    }

    /**
     * Heart rate per R26 burst from the 25 Hz compact optical waveform (**experimental**): bursts are runs of
     * consecutive seconds with the same burst counter; per burst of at least [minSeconds] s: median removed,
     * band-pass 0.6-3.3 Hz, inverted, peaks ≥ 0.33 s apart with prominence ≥ 0.3 sd, 60 / median IBI.
     * Twin of `hr_from_r26`.
     */
    fun hrFromR26(records: List<Pair<RecordHeader, Whoop5Record.CompactOptical>>, fs: Double = 25.0,
                  minSeconds: Int = 12): List<R26Burst> {
        val seen = HashSet<Long>()
        val rows = records.filter { it.first.layout == 26 && it.second.samples.isNotEmpty() }
            .sortedWith(compareBy({ it.first.unix }, { it.first.recordIndex })).filter { seen.add(it.first.recordIndex) }
        val bursts = mutableListOf<MutableList<Pair<RecordHeader, Whoop5Record.CompactOptical>>>()
        for (r in rows) {
            val last = bursts.lastOrNull()?.last()
            if (last != null && r.first.unix == last.first.unix + 1 && r.second.burstCounter == last.second.burstCounter)
                bursts.last().add(r) else bursts.add(mutableListOf(r))
        }
        return bursts.map { b ->
            val x = b.flatMap { r -> r.second.samples.map { it.toDouble() } }
            var beats = 0; var hr: Double? = null
            if (x.size >= fs * minSeconds) {
                val med = medianD(x)
                val y = bandpass(x.map { it - med }, fs, 0.6, 3.3).map { -it }
                val mean = sumSeq(y) / y.size
                val sd = sqrt(sumSeq(y.map { (it - mean) * (it - mean) }) / y.size)
                val peaks = findPeaks(y, (fs * 0.33).toInt(), 0.3 * sd)
                val ibi = peaks.zipWithNext { p, q -> (q - p) / fs }.filter { it > 0.3 && it < 2.0 }
                beats = peaks.size
                if (ibi.size >= 5) hr = 60.0 / medianD(ibi)
            }
            R26Burst(b.first().first.unix, b.last().first.unix, b.size, b.first().second.burstCounter, beats, hr)
        }
    }

    /** Neumaier-compensated sum: the algorithm Python's built-in sum() uses for floats since 3.12. */
    private fun sumSeq(v: List<Double>): Double {
        var s = 0.0; var c = 0.0
        for (x in v) {
            val t = s + x
            c += if (abs(s) >= abs(x)) (s - t) + x else (x - t) + s
            s = t
        }
        return s + c
    }

    private fun medianD(v: List<Double>): Double {
        val s = v.sorted(); val m = s.size / 2
        return if (s.size % 2 == 1) s[m] else (s[m - 1] + s[m]) / 2
    }
}
