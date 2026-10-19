package io.github.leonardseo.whoop5

import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.sin
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** Same inputs and expected values as python/tests/test_experimental.py and the Swift ParityTests. */
class ExperimentalTest {
    private fun state(t: Int): String =
        if ((t in 300 until 2000 && t !in 1000 until 1060) || t in 2900 until 4000) "SLEEP" else if (t % 2 == 1) "STILL" else "WAKE"

    private fun night(): List<Pair<RecordHeader, R18>> = (0 until 4000).map { t ->
        val st = state(t)
        val bits = when (st) { "SLEEP" -> 0x20; "STILL" -> 0x10; else -> 0 }
        val hr = if (t == 500) 0 else if (st == "SLEEP") 48 + t % 9 else 70
        RecordHeader(47, 18, 0x80, t.toLong(), 10000L + t, 0) to
            R18(hr, emptyList(), 0, 0, 0f, Triple(0f, 0f, 1f), 0, 0, 0, 0, 0, 0, 3300 + t / 100, bits, 0)
    }

    private fun r26Records(): List<Pair<RecordHeader, Whoop5Record.CompactOptical>> {
        val x = (0 until 30 * 25).map { i -> 100000L + 2 * i - (if (i % 20 < 3) 800 else 0) }
        fun rec(unix: Long, idx: Long, burst: Int, k: Int) =
            RecordHeader(47, 26, 0x80, idx, unix, 0) to
                Whoop5Record.CompactOptical(burst, x.subList(25 * k, 25 * k + 25), 0f, 0, 0, 0)
        val recs = (0 until 30).map { rec(5000L + it, it.toLong(), 3, it) }.toMutableList()
        recs.add(recs[4])
        recs += (0 until 5).map { rec(6000L + it, 100L + it, 4, it) }
        return recs
    }

    @Test fun sleepPeriods() {
        val p = Whoop5Experimental.sleepPeriods(night())
        assertEquals(1, p.size)
        assertEquals(listOf(10300L, 11999L), listOf(p[0].onsetUnix, p[0].offsetUnix))
        assertEquals(listOf(1700, 1640, 1700, 48), listOf(p[0].durationS, p[0].asleepS, p[0].records, p[0].hrMin))
        assertEquals(52.63802236609771, p[0].hrMean!!, 1e-9)
        assertEquals(emptyList(), Whoop5Experimental.sleepPeriods(emptyList()))
    }

    @Test fun respiratoryRate() {
        val rr = (0 until 45).flatMap { listOf(950, 1000, 1050, 1000) }.toMutableList()
        rr[20] = 250; rr[60] = 1500
        val w = Whoop5Experimental.respiratoryRate(rr)
        assertEquals(listOf(Triple(0.0, 60.0, 59), Triple(60.0, 120.0, 60)), w.map { Triple(it.startS, it.endS, it.beats) })
        assertEquals(15.3, w[0].breathsPerMin!!, 1e-9)
        assertEquals(15.0, w[1].breathsPerMin!!, 1e-9)
        assertEquals(0.16599567526638082, w[0].peakFraction!!, 1e-6)
        assertEquals(0.1985737846532536, w[1].peakFraction!!, 1e-6)
        assertEquals(emptyList(), Whoop5Experimental.respiratoryRate(List(50) { 1000 }))
        val flat = Whoop5Experimental.respiratoryRate(List(70) { 1000 })
        assertEquals(1, flat.size)
        assertNull(flat[0].breathsPerMin)
    }

    @Test fun skinTemp() {
        val s = Whoop5Experimental.skinTempBaseline(night())[0]
        assertEquals(listOf(10300L, 11999L), listOf(s.onsetUnix, s.offsetUnix))
        assertEquals(1700, s.samples)
        assertEquals(33.03, s.minC!!, 1e-12); assertEquals(33.19, s.maxC!!, 1e-12)
        assertEquals(33.11, s.meanC!!, 1e-9); assertEquals(0.0489897948556632, s.sdC!!, 1e-9)
        assertNull(s.deviationC)
        assertEquals(0.11, Whoop5Experimental.skinTempBaseline(night(), baselineC = 33.0)[0].deviationC!!, 1e-9)
        val periods = listOf(
            Whoop5Experimental.SleepPeriod(10000, 10999, 1000, 0, 0, null, null),
            Whoop5Experimental.SleepPeriod(11000, 11999, 1000, 0, 0, null, null))
        val (a, b) = Whoop5Experimental.skinTempBaseline(night(), periods = periods)
        assertEquals(33.045, a.meanC!!, 1e-9); assertNull(a.deviationC)
        assertEquals(33.045, b.baselineC!!, 1e-9); assertEquals(0.1, b.deviationC!!, 1e-9)
    }

    @Test fun hrFromR26() {
        val out = Whoop5Experimental.hrFromR26(r26Records())
        assertEquals(listOf(listOf(5000L, 5029L, 30L, 3L, 37L), listOf(6000L, 6004L, 5L, 4L, 0L)),
            out.map { listOf(it.startUnix, it.endUnix, it.seconds.toLong(), it.burstCounter.toLong(), it.beats.toLong()) })
        assertEquals(75.0, out[0].heartRateBpm!!, 1e-9)
        assertNull(out[1].heartRateBpm)
    }

    @Test fun findPeaksMatchesScipy() {
        val y = listOf(0.0, 2.0, 1.0, 3.0, 1.0, 0.0, 5.0, 4.0, 5.0, 0.0)
        assertEquals(listOf(1, 3, 6, 8), Whoop5Experimental.findPeaks(y))
        assertEquals(listOf(3, 8), Whoop5Experimental.findPeaks(y, distance = 3))
        assertEquals(listOf(6, 8), Whoop5Experimental.findPeaks(y, prominence = 4.0))
    }

    @Test fun bandpassPasses1HzRejectsDrift() {
        val one = Whoop5Experimental.bandpass(List(250) { sin(2 * PI * it / 25) }, 25.0, 0.6, 3.3)
        assertTrue(one.subList(50, 200).max() > 0.85)
        val slow = Whoop5Experimental.bandpass(List(250) { sin(2 * PI * 0.1 * it / 25) }, 25.0, 0.6, 3.3)
        assertTrue(slow.subList(50, 200).maxOf { abs(it) } < 0.01)
    }
}

/** Opt-in: WHOOP5_FRAMES=<frames.jsonl> prints the experimental metrics for a real capture (for cross-checks). */
class ExperimentalCorpusReport {
    @Test fun report() {
        val path = System.getenv("WHOOP5_FRAMES") ?: return
        val r18 = mutableListOf<Pair<RecordHeader, R18>>()
        val r26 = mutableListOf<Pair<RecordHeader, Whoop5Record.CompactOptical>>()
        java.io.File(path).forEachLine { line ->
            val hex = Regex("\"hex\": ?\"([0-9a-f]+)\"").find(line)?.groupValues?.get(1) ?: return@forEachLine
            val raw = ByteArray(hex.length / 2) { hex.substring(2 * it, 2 * it + 2).toInt(16).toByte() }
            val p = try { Whoop5Decoder.decode(raw) } catch (e: Exception) { return@forEachLine }
            if (p is Whoop5Packet.Record) when (val r = p.record) {
                is Whoop5Record.Biometric -> r18.add(p.header to r.r18)
                is Whoop5Record.CompactOptical -> r26.add(p.header to r)
                else -> {}
            }
        }
        Whoop5Experimental.sleepPeriods(r18).forEach { println("SLEEP $it") }
        val rr = r18.sortedBy { it.first.unix }.distinctBy { it.first.unix }.flatMap { it.second.rrMs }
        Whoop5Experimental.respiratoryRate(rr).take(5).forEach { println("RESP $it") }
        Whoop5Experimental.skinTempBaseline(r18).forEach { println("SKIN $it") }
        Whoop5Experimental.hrFromR26(r26).forEach { println("R26 ${it.startUnix} ${it.heartRateBpm}") }
    }
}
