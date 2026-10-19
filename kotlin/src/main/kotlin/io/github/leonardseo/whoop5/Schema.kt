package io.github.leonardseo.whoop5

/** Name tables from the bundled canonical `whoop5_protocol.json` (byte-identical to `protocol/`). */
object Whoop5Schema {
    @Suppress("UNCHECKED_CAST")
    val json: Map<String, Any?> by lazy {
        val text = Whoop5Schema::class.java.getResourceAsStream("/whoop5_protocol.json")!!
            .bufferedReader(Charsets.UTF_8).use { it.readText() }
        MiniJson.parse(text) as Map<String, Any?>
    }

    @Suppress("UNCHECKED_CAST")
    private fun table(name: String): Map<String, Any?> = json[name] as? Map<String, Any?> ?: emptyMap()

    fun commandName(n: Int): String = table("commands")[n.toString()] as? String ?: "UNKNOWN_$n"
    fun eventName(n: Int): String = table("events")[n.toString()] as? String ?: "UNKNOWN_$n"
    fun packetName(n: Int): String = table("packet_types")[n.toString()] as? String ?: "UNKNOWN_$n"

    /** Commands that can brick, wipe or permanently alter a strap. A client should never send these. */
    val destructiveCommands: Set<Int> by lazy {
        (table("commands")["destructive"] as? List<*>)?.mapNotNull { (it as? Number)?.toInt() }?.toSet() ?: emptySet()
    }
}

/** Minimal JSON reader (objects, arrays, strings, numbers, booleans, null) so the library has no dependencies. */
object MiniJson {
    fun parse(text: String): Any? = Parser(text).run { val v = value(); ws(); v }

    private class Parser(val s: String) {
        var i = 0
        fun ws() { while (i < s.length && s[i].isWhitespace()) i++ }
        fun value(): Any? {
            ws()
            return when (val c = s[i]) {
                '{' -> obj()
                '[' -> arr()
                '"' -> str()
                't' -> { i += 4; true }
                'f' -> { i += 5; false }
                'n' -> { i += 4; null }
                else -> if (c == '-' || c.isDigit()) num() else error("unexpected '$c' at $i")
            }
        }
        fun obj(): Map<String, Any?> {
            val m = LinkedHashMap<String, Any?>(); i++; ws()
            if (s[i] == '}') { i++; return m }
            while (true) {
                ws(); val k = str(); ws(); i++ // ':'
                m[k] = value(); ws()
                if (s[i++] == '}') return m
            }
        }
        fun arr(): List<Any?> {
            val l = ArrayList<Any?>(); i++; ws()
            if (s[i] == ']') { i++; return l }
            while (true) {
                l.add(value()); ws()
                if (s[i++] == ']') return l
            }
        }
        fun str(): String {
            val b = StringBuilder(); i++
            while (s[i] != '"') {
                if (s[i] == '\\') {
                    i++
                    when (val e = s[i]) {
                        'n' -> b.append('\n'); 't' -> b.append('\t'); 'r' -> b.append('\r')
                        'b' -> b.append('\b'); 'f' -> b.append('\u000c')
                        'u' -> { b.append(s.substring(i + 1, i + 5).toInt(16).toChar()); i += 4 }
                        else -> b.append(e)
                    }
                } else b.append(s[i])
                i++
            }
            i++
            return b.toString()
        }
        fun num(): Number {
            val start = i
            while (i < s.length && (s[i].isDigit() || s[i] in "+-.eE")) i++
            val t = s.substring(start, i)
            return if (t.any { it in ".eE" }) t.toDouble() else t.toLong()
        }
    }
}
