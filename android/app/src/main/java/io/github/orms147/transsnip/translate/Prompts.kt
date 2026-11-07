package io.github.orms147.transsnip.translate

/**
 * Prompt text shared with the desktop app (transsnip/translate/prompts.py).
 * Keep the wording in sync: each rule exists because a model misbehaved
 * without it (answering in the source language, "fixing" fragmented text…).
 */
object Prompts {
    // BCP-47 → English name. LLMs follow language *names* more reliably than tags.
    private val LANG_NAMES = mapOf(
        "vi" to "Vietnamese",
        "en" to "English",
        "ja" to "Japanese",
        "ko" to "Korean",
        "zh-Hans" to "Simplified Chinese",
        "zh-Hant" to "Traditional Chinese",
    )

    fun langName(code: String?): String = LANG_NAMES[code.orEmpty()] ?: code.orEmpty()

    fun systemPrompt(target: String, source: String?): String {
        val t = langName(target)
        val parts = mutableListOf(
            "You are a professional translator. Translate the user's text into $t.",
            "Your ENTIRE response MUST be written in $t. Never reply in the " +
                "source language; if the text is already in $t, return it unchanged.",
            "Translate exactly what is given even if it is fragmented, incomplete, or " +
                "contains transcription/OCR errors — do NOT fix, rephrase, complete, or " +
                "comment on the source; just translate it as-is.",
            "Output ONLY the translation — no quotes, no markdown fences, no preface, " +
                "no explanation.",
            "Preserve formatting (line breaks, lists). Keep proper nouns and code " +
                "identifiers in their original form.",
        )
        parts += contextLines(source)
        return parts.joinToString("\n")
    }

    /**
     * Bare fallback for when the full prompt gets an empty reply: some models
     * (tencent/hy-mt2 on OpenRouter) hide their whole answer as reasoning under
     * the stricter instructions, deterministically for a given input.
     */
    fun minimalSystemPrompt(target: String, source: String?): String =
        (listOf("You are a professional translator. Translate the user's text into ${langName(target)}.") +
            contextLines(source)).joinToString("\n")

    /** Small models weigh the user turn far more than the system prompt. */
    fun userTurn(text: String, target: String): String =
        "Translate into ${langName(target)}:\n\n$text"

    /** Screen text: many separate short lines in one request, numbered so each answer maps back. */
    fun batchSystemPrompt(target: String, source: String?, minimal: Boolean): String =
        (if (minimal) minimalSystemPrompt(target, source) else systemPrompt(target, source)) + "\n" +
            "The text comes from a phone screen as numbered lines \"[n] text\": separate comments, " +
            "names, buttons, labels and captions. Translate every line on its own and reply with " +
            "exactly one line per input line in the same \"[n] translation\" format, keeping each " +
            "number. Do not merge, split or skip lines."

    /** A one-line "batch": the plain prompt, no numbering to keep track of. */
    fun batchSingleSystem(target: String, source: String?, minimal: Boolean): String =
        if (minimal) minimalSystemPrompt(target, source) else systemPrompt(target, source)

    /**
     * A screen line's translation, not a chat answer: one line, and not wildly
     * longer than the source (Vietnamese runs ~3x the characters of Chinese).
     */
    fun plausibleTranslation(source: String, answer: String): Boolean {
        if (answer.isBlank() || answer.lines().count { it.isNotBlank() } > maxOf(2, source.lines().size + 1)) return false
        return answer.length <= maxOf(40, source.length * 5)
    }

    fun batchUserTurn(lines: List<String>, target: String): String =
        "Translate into ${langName(target)}:\n\n" +
            lines.mapIndexed { i, s -> "[${i + 1}] $s" }.joinToString("\n")

    /**
     * Worth sending to the model? Not for numbers, times, emoji, or text that
     * is already in the target language (Vietnamese is told from English by
     * its diacritics; both are "Latin" to [LangDetect]).
     */
    fun needsTranslation(text: String, target: String): Boolean {
        val t = text.trim()
        if (t.count { it.isLetter() } < 2 && t.none { it in '㐀'..'鿿' }) return false
        val hasHan = t.any { it in '㐀'..'鿿' }
        // URLs, handles, file names: one Latin token with . / _ @ :
        if (!hasHan && t.none { it.isWhitespace() } && t.any { it in "./_@:" }) return false
        val lang = LangDetect.detect(t) ?: return false
        return when (target.substringBefore('-')) {
            "vi" -> !(lang == "en" && t.any { it.lowercaseChar() in VIET })
            "en" -> lang != "en"
            "zh" -> lang != "zh-Hans"
            else -> true
        }
    }

    private const val VIET = "ăâđêôơưàảãáạằẳẵắặầẩẫấậèẻẽéẹềểễếệìỉĩíịòỏõóọồổỗốộờởỡớợùủũúụừửữứựỳỷỹýỵ"

    private fun contextLines(source: String?): List<String> =
        if (source.isNullOrEmpty()) emptyList() else listOf("The source is ${langName(source)}.")

    /** Output still mostly in a CJK script the (Latin) target doesn't use. */
    fun looksUntranslated(output: String, target: String): Boolean {
        if (target.substringBefore('-') in setOf("zh", "ja", "ko")) return false
        return LangDetect.detect(output)?.substringBefore('-') in setOf("zh", "ja", "ko")
    }
}

/** Script-based language guess — enough to tell zh / ja / ko / en apart. */
object LangDetect {
    fun detect(text: String): String? {
        var han = 0
        var kana = 0
        var hangul = 0
        var latin = 0
        for (c in text) {
            when (c) {
                in '぀'..'ヿ' -> kana++
                in '가'..'힯', in 'ᄀ'..'ᇿ' -> hangul++
                in '㐀'..'鿿', in '豈'..'﫿' -> han++
                else -> if (c.isLetter() && c.code < 0x250) latin++
            }
        }
        val cjk = han + kana + hangul
        // A Vietnamese translation may keep a CJK name: only call it CJK when
        // CJK characters are a real share of the letters.
        return when {
            cjk == 0 && latin == 0 -> null
            cjk * 3 < latin -> "en"
            kana > 0 -> "ja"
            hangul > han -> "ko"
            han > 0 -> "zh-Hans"
            else -> "en"
        }
    }
}
