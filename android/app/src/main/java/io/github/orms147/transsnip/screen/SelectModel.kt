package io.github.orms147.transsnip.screen

/**
 * The text on a frozen screen, as something you can select like in a text
 * field: every character (or OCR'd glyph) with its box, in reading order.
 * Plain Kotlin — no Android types — so it is unit-tested directly.
 */
class Glyph(val text: String, val l: Int, val t: Int, val r: Int, val b: Int) {
    val cx get() = (l + r) / 2
    val cy get() = (t + b) / 2
}

/**
 * One visual line. [source]: which piece of text it came from — lines of the
 * same source are a wrapped paragraph and join without a line break.
 * [hardBreak]: the text itself had a line break before this line.
 */
class TextLine(val glyphs: List<Glyph>, val source: Int, val hardBreak: Boolean = false) {
    val l = glyphs.minOf { it.l }
    val t = glyphs.minOf { it.t }
    val r = glyphs.maxOf { it.r }
    val b = glyphs.maxOf { it.b }
}

class SelectModel(input: List<TextLine>) {

    /** Lines in reading order: rows top to bottom, left to right within a row. */
    val lines: List<TextLine> = order(input.filter { it.glyphs.isNotEmpty() })
    val glyphs: List<Glyph> = lines.flatMap { it.glyphs }
    private val lineOf = IntArray(glyphs.size)
    private val lineStart = IntArray(lines.size)

    init {
        var k = 0
        lines.forEachIndexed { li, line ->
            lineStart[li] = k
            repeat(line.glyphs.size) { lineOf[k++] = li }
        }
    }

    val isEmpty get() = glyphs.isEmpty()
    val all get() = glyphs.indices

    fun lineIndex(glyph: Int) = lineOf[glyph]
    fun lineRange(line: Int) = lineStart[line] until lineStart[line] + lines[line].glyphs.size

    /** Every line of [line]'s paragraph (same source, adjacent in reading order). */
    fun paragraphRange(line: Int): IntRange {
        val src = lines[line].source
        var a = line
        while (a > 0 && lines[a - 1].source == src) a--
        var z = line
        while (z < lines.size - 1 && lines[z + 1].source == src) z++
        return lineStart[a]..lineRange(z).last
    }

    /** The glyph under (x, y), allowing [slack] px around it; −1 if none. */
    fun hit(x: Int, y: Int, slack: Int): Int {
        var best = -1
        var bestD = Long.MAX_VALUE
        for ((i, g) in glyphs.withIndex()) {
            if (x < g.l - slack || x > g.r + slack || y < g.t - slack || y > g.b + slack) continue
            val d = dist(g, x, y)
            if (d < bestD) { bestD = d; best = i }
        }
        return best
    }

    /**
     * The glyph a drag at (x, y) means: the closest line (by height first —
     * fingers drift sideways along a line), then the closest glyph in it.
     */
    fun nearest(x: Int, y: Int): Int {
        if (glyphs.isEmpty()) return -1
        var li = 0
        var bestD = Long.MAX_VALUE
        for ((i, line) in lines.withIndex()) {
            val dy = if (y < line.t) line.t - y else if (y > line.b) y - line.b else 0
            val dx = if (x < line.l) line.l - x else if (x > line.r) x - line.r else 0
            val d = dy.toLong() * dy * 4 + dx.toLong() * dx
            if (d < bestD) { bestD = d; li = i }
        }
        val range = lineRange(li)
        return range.minByOrNull { val g = glyphs[it]; val dx = (g.cx - x).toLong(); dx * dx } ?: range.first
    }

    /** What gets copied: wrapped lines rejoined, separate texts on their own lines. */
    fun text(range: IntRange): String {
        if (range.isEmpty() || glyphs.isEmpty()) return ""
        val sb = StringBuilder()
        var prevLine = -1
        for (i in range.first.coerceAtLeast(0)..range.last.coerceAtMost(glyphs.size - 1)) {
            val li = lineOf[i]
            val g = glyphs[i]
            if (prevLine != -1 && li != prevLine) {
                val trimmed = sb.trimEnd()
                sb.setLength(trimmed.length)
                val line = lines[li]
                if (line.source == lines[prevLine].source && !line.hardBreak) {
                    if (sb.isNotEmpty() && !isCjk(sb.last()) && !isCjk(g.text.first())) sb.append(' ')
                } else {
                    sb.append('\n')
                }
            }
            sb.append(g.text)
            prevLine = li
        }
        return sb.toString().trim()
    }

    private fun dist(g: Glyph, x: Int, y: Int): Long {
        val dx = (g.cx - x).toLong()
        val dy = (g.cy - y).toLong()
        return dx * dx + dy * dy
    }

    companion object {
        fun isCjk(c: Char) = c.code >= 0x2E80 && c.code < 0xFF00 || c.isSurrogate()

        /**
         * Rows: a line joins the current row when its middle is within the
         * row's first line (side-by-side labels, a name next to a date).
         */
        private fun order(input: List<TextLine>): List<TextLine> {
            val byTop = input.sortedBy { it.t }
            val out = ArrayList<TextLine>()
            var row = ArrayList<TextLine>()
            for (line in byTop) {
                val head = row.firstOrNull()
                if (head != null && (line.t + line.b) / 2 > head.b) {
                    out += row.sortedBy { it.l }
                    row = ArrayList()
                }
                row += line
            }
            out += row.sortedBy { it.l }
            return out
        }

        /**
         * Splits a word box from OCR into one box per character: OCR gives
         * words, not characters, and characters of one font are close
         * enough to equal width for picking where a selection starts.
         */
        fun splitEvenly(text: String, l: Int, t: Int, r: Int, b: Int): List<Glyph> {
            val chars = codepoints(text)
            if (chars.isEmpty()) return emptyList()
            val w = (r - l).toFloat() / chars.size
            return chars.mapIndexed { i, c ->
                Glyph(c, (l + w * i).toInt(), t, (l + w * (i + 1)).toInt(), b)
            }
        }

        fun codepoints(text: String): List<String> {
            val out = ArrayList<String>()
            var i = 0
            while (i < text.length) {
                val n = Character.charCount(text.codePointAt(i))
                out += text.substring(i, i + n)
                i += n
            }
            return out
        }
    }
}
