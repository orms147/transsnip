package io.github.orms147.transsnip.zh

/** One character of a token. `numbered` = "zhang3" (hv_best key form, ü → v). */
data class Syllable(val char: Char, val numbered: String) {
    /** 1-4, 5 = neutral, 0 = not a Han character. */
    val tone: Int get() = if (numbered.isEmpty()) 0 else numbered.last().digitToIntOrNull() ?: 5
    val marked: String get() = Pinyin.mark(numbered)
}

data class Token(val text: String, val syllables: List<Syllable>) {
    /** Contains Chinese characters — clickable, looked up. */
    val isWord: Boolean get() = syllables.any { it.tone != 0 }
    val pinyin: String get() = syllables.filter { it.tone != 0 }.joinToString(" ") { it.marked }
}

object Pinyin {
    // Pleco-style tone colours, same as the desktop app (learning/zh/text.py).
    val TONE_COLORS = mapOf(1 to 0xFFE5484D.toInt(), 2 to 0xFF30A46C.toInt(),
        3 to 0xFF3E8EF7.toInt(), 4 to 0xFFA855F7.toInt(), 5 to 0xFF8B8D98.toInt())

    private val MARKS = mapOf(
        'a' to "āáǎà", 'e' to "ēéěè", 'i' to "īíǐì", 'o' to "ōóǒò", 'u' to "ūúǔù", 'ü' to "ǖǘǚǜ",
    )

    fun isHan(c: Char): Boolean = c in '㐀'..'鿿' || c in '豈'..'﫿'

    /** "zhang3" → "zhǎng", "nv3" → "nǚ", "de5" → "de". */
    fun mark(numbered: String): String {
        if (numbered.isEmpty()) return ""
        val tone = numbered.last().digitToIntOrNull()
        val base = (if (tone != null) numbered.dropLast(1) else numbered).replace('v', 'ü')
        if (tone == null || tone !in 1..4) return base
        // Standard rule: a or e takes the mark; in "ou" the o; else the last vowel.
        val idx = when {
            'a' in base -> base.indexOf('a')
            'e' in base -> base.indexOf('e')
            "ou" in base -> base.indexOf('o')
            else -> base.indexOfLast { it in MARKS }
        }
        if (idx < 0) return base
        return base.substring(0, idx) + MARKS.getValue(base[idx])[tone - 1] + base.substring(idx + 1)
    }
}
