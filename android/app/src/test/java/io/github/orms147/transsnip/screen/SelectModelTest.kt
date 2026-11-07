package io.github.orms147.transsnip.screen

import org.junit.Assert.assertEquals
import org.junit.Test

class SelectModelTest {

    private fun line(text: String, x: Int, y: Int, source: Int, hard: Boolean = false, w: Int = 10) =
        TextLine(SelectModel.codepoints(text).mapIndexed { i, c -> Glyph(c, x + i * w, y, x + (i + 1) * w, y + 20) }, source, hard)

    @Test
    fun readingOrderAndJoin() {
        // Given out of order; same row (name + date) side by side.
        val m = SelectModel(listOf(
            line("回复", 0, 100, 3),
            line("9月8日", 200, 52, 2),
            line("馬也", 0, 50, 1),
            line("English Subs", 0, 0, 0),
        ))
        assertEquals("English Subs\n馬也\n9月8日\n回复", m.text(m.all))
    }

    @Test
    fun wrappedLinesOfOneSourceJoin() {
        val m = SelectModel(listOf(
            line("Sea Island", 0, 0, 0),
            line("You 海嶼", 0, 30, 0),
            line("你好", 0, 60, 0),
            line("new", 0, 90, 0, hard = true),
        ))
        assertEquals("Sea Island You 海嶼你好\nnew", m.text(m.all))
    }

    @Test
    fun nearestPrefersTheLineThenTheColumn() {
        val m = SelectModel(listOf(line("abcdef", 0, 0, 0), line("ghijkl", 0, 40, 1)))
        // Finger a bit below line 1, at the 3rd char.
        assertEquals(2, m.nearest(25, 24))
        // Far right of line 2 → its last char.
        assertEquals(11, m.nearest(500, 50))
        assertEquals("cdefgh", m.text(2..7).replace("\n", ""))
        assertEquals("cdef\ngh", m.text(2..7))
    }

    @Test
    fun paragraphRangeCoversSameSourceLines() {
        val m = SelectModel(listOf(line("ab", 0, 0, 0), line("cd", 0, 30, 0), line("ef", 0, 60, 1)))
        assertEquals(0..3, m.paragraphRange(1))
        assertEquals(4..5, m.paragraphRange(2))
    }

    @Test
    fun splitEvenlyKeepsEmojiWhole() {
        val g = SelectModel.splitEvenly("高😂", 0, 0, 20, 10)
        assertEquals(listOf("高", "😂"), g.map { it.text })
        assertEquals(10, g[1].l)
    }
}
