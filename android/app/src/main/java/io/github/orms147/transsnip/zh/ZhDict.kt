package io.github.orms147.transsnip.zh

import android.content.Context
import android.database.sqlite.SQLiteDatabase
import java.io.File

data class DictEntry(val pinyin: String, val meanings: List<String>)

data class CharInfo(
    val char: Char,
    val hanviet: String,
    val hanvietAll: String,
    val radical: String,
    val components: List<String>,
    val etymType: String,
    val etymHint: String,
    val meanings: List<String>,
)

/**
 * Offline Chinese–Vietnamese dictionary (assets/zh.sqlite, built by
 * scripts/build_android_zh.py from the desktop data). Read-only; every query
 * is an indexed lookup of a few microseconds.
 */
class ZhDict private constructor(private val db: SQLiteDatabase) {

    // ── segmentation + pinyin ────────────────────────────────────────────

    /**
     * Words with per-character pinyin. Han runs are segmented by bidirectional
     * maximum matching against the dictionary (fewest words wins, then fewest
     * single characters); other runs (Latin, digits, punctuation) pass through
     * as non-word tokens so the text renders verbatim.
     */
    fun tokenize(text: String): List<Token> {
        val out = mutableListOf<Token>()
        var i = 0
        while (i < text.length) {
            val han = Pinyin.isHan(text[i])
            var j = i
            while (j < text.length && Pinyin.isHan(text[j]) == han) j++
            val run = text.substring(i, j)
            if (han) segment(run).forEach { out += wordToken(it) } else out += otherTokens(run)
            i = j
        }
        applySandhi(out)
        return out
    }

    private fun otherTokens(run: String): List<Token> =
        Regex("[A-Za-z0-9]+|\\s+|.").findAll(run).map { m ->
            Token(m.value, m.value.map { Syllable(it, "") })
        }.toList()

    private fun segment(run: String): List<String> {
        val fwd = mutableListOf<String>()
        var i = 0
        while (i < run.length) {
            val w = longestAt(run, i, forward = true)
            fwd += w
            i += w.length
        }
        val bwd = ArrayDeque<String>()
        var j = run.length
        while (j > 0) {
            val w = longestAt(run, j, forward = false)
            bwd.addFirst(w)
            j -= w.length
        }
        val back = bwd.toList()
        fun singles(l: List<String>) = l.count { it.length == 1 }
        return when {
            fwd.size != back.size -> if (fwd.size < back.size) fwd else back
            singles(fwd) < singles(back) -> fwd
            else -> back
        }
    }

    /** Longest dictionary word starting at `pos` (forward) or ending at `pos`. */
    private fun longestAt(run: String, pos: Int, forward: Boolean): String {
        val maxLen = if (forward) minOf(MAX_WORD, run.length - pos) else minOf(MAX_WORD, pos)
        if (maxLen < 2) return if (forward) run.substring(pos, pos + 1) else run.substring(pos - 1, pos)
        val candidates = (2..maxLen).map { n ->
            if (forward) run.substring(pos, pos + n) else run.substring(pos - n, pos)
        }
        val found = HashSet<String>()
        db.rawQuery(
            "SELECT word FROM word_py WHERE word IN (${candidates.joinToString(",") { "?" }})",
            candidates.toTypedArray(),
        ).use { c -> while (c.moveToNext()) found += c.getString(0) }
        return candidates.lastOrNull { it in found }
            ?: if (forward) run.substring(pos, pos + 1) else run.substring(pos - 1, pos)
    }

    /** `word` with its dictionary pinyin (no segmentation) — for the word card. */
    fun annotate(word: String): Token = wordToken(word)

    private fun wordToken(word: String): Token {
        val readings = if (word.length > 1) wordPinyin(word) else null
        val syllables = word.mapIndexed { k, ch ->
            Syllable(ch, readings?.getOrNull(k) ?: charPinyin(ch))
        }
        return Token(word, syllables)
    }

    private fun wordPinyin(word: String): List<String>? =
        db.rawQuery("SELECT pinyin FROM word_py WHERE word=?", arrayOf(word)).use { c ->
            if (c.moveToFirst()) c.getString(0).split(' ').takeIf { it.size == word.length } else null
        }

    private fun charPinyin(ch: Char): String =
        db.rawQuery("SELECT pinyin FROM char_py WHERE char=?", arrayOf(ch.toString())).use { c ->
            if (c.moveToFirst()) c.getString(0) else "?5"
        }

    /** 一 / 不 standing alone change tone before the next syllable (一定 → yí). */
    private fun applySandhi(tokens: MutableList<Token>) {
        for (k in tokens.indices) {
            val t = tokens[k]
            if (t.text != "一" && t.text != "不") continue
            // Only when a Chinese word follows directly ("一，" or "不 OK" stay as is).
            val nextTok = tokens.subList(k + 1, tokens.size).firstOrNull { it.text.isNotBlank() } ?: continue
            if (!nextTok.isWord) continue
            val next = nextTok.syllables.first().tone
            val numbered = when {
                t.text == "不" && next == 4 -> "bu2"
                t.text == "一" && next == 4 -> "yi2"
                t.text == "一" && next in 1..3 -> "yi4"
                else -> continue
            }
            tokens[k] = Token(t.text, listOf(Syllable(t.text[0], numbered)))
        }
    }

    // ── Hán-Việt ─────────────────────────────────────────────────────────

    /** Reading of `ch` as pronounced `numbered`; falls back to its common reading. */
    fun hanviet(ch: Char, numbered: String): String {
        db.rawQuery("SELECT reading FROM hv_best WHERE char=? AND pinyin=?",
            arrayOf(ch.toString(), numbered.lowercase())).use { c ->
            if (c.moveToFirst() && !c.getString(0).isNullOrEmpty()) return c.getString(0)
        }
        db.rawQuery("SELECT primary_reading, all_readings FROM hvchar WHERE char=?",
            arrayOf(ch.toString())).use { c ->
            if (!c.moveToFirst()) return ""
            val primary = c.getString(0).orEmpty()
            return primary.ifEmpty { c.getString(1).orEmpty().split(',').first() }.trim()
        }
    }

    fun tokenHanviet(t: Token): String =
        t.syllables.filter { it.tone != 0 }.joinToString(" ") { hanviet(it.char, it.numbered).ifEmpty { it.char.toString() } }

    /** "实习不久，老董事长" → "thực tập bất cửu, lão đổng sự trưởng". */
    fun sentenceHanviet(tokens: List<Token>): String {
        val parts = mutableListOf<String>()
        for (t in tokens) {
            when {
                t.isWord -> parts += tokenHanviet(t)
                t.text.isNotBlank() -> {
                    val mapped = t.text.map { PUNCT[it] ?: it.toString() }.joinToString("")
                    if (parts.isNotEmpty() && mapped in ATTACH) parts[parts.size - 1] += mapped
                    else parts += mapped
                }
            }
        }
        return parts.joinToString(" ")
    }

    // ── words + characters ───────────────────────────────────────────────

    /** Entries for `word`; the one matching `numbered` pinyin (exact case first) leads. */
    fun lookup(word: String, numbered: String = ""): List<DictEntry> {
        val rows = mutableListOf<DictEntry>()
        db.rawQuery("SELECT pinyin, vi FROM words WHERE simp=? OR trad=?", arrayOf(word, word)).use { c ->
            while (c.moveToNext()) {
                rows += DictEntry(c.getString(0), c.getString(1).split('/').map { it.trim() }
                    .filter { it.isNotEmpty() && !it.startsWith("LT:") })
            }
        }
        if (numbered.isEmpty()) return rows
        fun norm(p: String) = p.replace("u:", "v")
        return rows.sortedBy { e ->
            when {
                norm(e.pinyin) == numbered -> 0
                norm(e.pinyin).lowercase() == numbered -> 1
                else -> 2
            }
        }
    }

    fun hsk(word: String): Int? =
        db.rawQuery("SELECT level FROM hsk WHERE word=?", arrayOf(word)).use { c ->
            if (c.moveToFirst()) c.getInt(0) else null
        }

    fun charInfo(s: Syllable): CharInfo {
        var radical = ""
        var decomp = ""
        var etymType = ""
        var etymHint = ""
        db.rawQuery("SELECT radical, decomposition, etym_type, etym_hint FROM chars WHERE char=?",
            arrayOf(s.char.toString())).use { c ->
            if (c.moveToFirst()) {
                radical = c.getString(0).orEmpty()
                decomp = c.getString(1).orEmpty()
                etymType = c.getString(2).orEmpty()
                etymHint = c.getString(3).orEmpty()
            }
        }
        val all = db.rawQuery("SELECT all_readings, primary_reading FROM hvchar WHERE char=?",
            arrayOf(s.char.toString())).use { c ->
            if (c.moveToFirst()) c.getString(0).orEmpty().ifEmpty { c.getString(1).orEmpty() } else ""
        }
        return CharInfo(
            char = s.char,
            hanviet = hanviet(s.char, s.numbered),
            hanvietAll = all,
            radical = radical.takeIf { it != "？" }.orEmpty(),
            // IDS "⿰女子" → [女, 子]: the ⿰⿱… operators render as boxes.
            components = decomp.filter { it !in '⿰'..'⿿' && it != '？' && it != '?' }
                .map { it.toString() },
            etymType = etymType,
            etymHint = etymHint,
            meanings = lookup(s.char.toString(), s.numbered).firstOrNull()?.meanings.orEmpty(),
        )
    }

    companion object {
        private const val MAX_WORD = 8
        private const val ASSET = "zh.sqlite"
        private val PUNCT = mapOf('，' to ",", '。' to ".", '！' to "!", '？' to "?", '：' to ":",
            '；' to ";", '、' to ",", '（' to "(", '）' to ")", '“' to "\"", '”' to "\"")
        private val ATTACH = setOf(",", ".", "!", "?", ":", ";", ")")

        @Volatile private var instance: ZhDict? = null

        /**
         * Opens (first call: copies out of the APK — SQLite needs a real file).
         * Call off the main thread. Null if the app was built without the data.
         */
        fun get(context: Context): ZhDict? {
            instance?.let { return it }
            synchronized(this) {
                instance?.let { return it }
                val app = context.applicationContext
                if (ASSET !in (app.assets.list("") ?: emptyArray())) return null
                val file = File(app.noBackupFilesDir, ASSET)
                // Re-copy after every app install/update (the data may have changed).
                val stamp = app.packageManager.getPackageInfo(app.packageName, 0).lastUpdateTime
                val prefs = app.getSharedPreferences("zh", Context.MODE_PRIVATE)
                if (!file.exists() || prefs.getLong("copied_at", 0) != stamp) {
                    val tmp = File(file.path + ".tmp")
                    app.assets.open(ASSET).use { input -> tmp.outputStream().use { input.copyTo(it) } }
                    tmp.renameTo(file)
                    prefs.edit().putLong("copied_at", stamp).apply()
                }
                val db = SQLiteDatabase.openDatabase(file.path, null,
                    SQLiteDatabase.OPEN_READONLY or SQLiteDatabase.NO_LOCALIZED_COLLATORS)
                return ZhDict(db).also { instance = it }
            }
        }

        /** The sentence of `text` containing text[start, end) (desktop: text.sentence_at). */
        fun sentenceAt(text: String, start: Int, end: Int): String {
            val ends = "。！？!?；;\n"
            var l = start
            while (l > 0 && text[l - 1] !in ends) l--
            var r = end
            while (r < text.length && text[r] !in ends) r++
            if (r < text.length) r++
            return text.substring(l, r).trim()
        }
    }
}
