package io.github.leonardseo.whoop5

import kotlin.math.abs
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
}
