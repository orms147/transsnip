package io.github.orms147.transsnip.zh

import io.github.orms147.transsnip.translate.Completer
import org.json.JSONObject

/** AI usage notes for a word (desktop: learning/zh/usage.py — same prompt). */
data class UsageNote(
    val meaningHere: String,
    val explanation: String,
    val grammar: List<String>,
    val examples: List<Triple<String, String, String>>,   // zh, pinyin, vi
    val collocations: List<String>,
    val confusables: List<Pair<String, String>>,
)

object Usage {
    private const val SYSTEM = "You are a patient Chinese teacher for Vietnamese learners. " +
        "Reply with ONE JSON object only — no markdown fences, no commentary."

    private val cache = HashMap<String, UsageNote>()   // per (word, sentence) for this process

    fun prompt(word: String, sentence: String): String = listOfNotNull(
        "Explain how the Chinese word「$word」is used, for a Vietnamese learner.",
        if (sentence.isNotEmpty() && sentence != word) "It appeared in this sentence: 「$sentence」" else "",
        "",
        "Return JSON with exactly these keys (all text in Vietnamese except Chinese/pinyin):",
        "{\"meaning_here\": \"<its meaning in the sentence above, or the main meaning>\",",
        " \"explanation\": \"<2-3 sentences: what it means, register, when to use it>\",",
        " \"grammar\": [\"<short usage/grammar pattern, e.g. 在…实习>\", \"...\"],",
        " \"examples\": [{\"zh\": \"<natural sentence>\", \"pinyin\": \"<pinyin with tone marks>\",",
        "               \"vi\": \"<Vietnamese translation>\"}],   // exactly 3, simple to medium",
        " \"collocations\": [\"<common word combination with it>\", \"...\"],",
        " \"confusables\": [{\"word\": \"<similar word>\", \"difference\": \"<how it differs>\"}]}",
    ).joinToString("\n")

    fun explain(completer: Completer, word: String, sentence: String): UsageNote {
        val key = "$word\u0000$sentence"
        synchronized(cache) { cache[key]?.let { return it } }
        val raw = completer.complete(SYSTEM, prompt(word, sentence))
        return parse(raw).also { synchronized(cache) { cache[key] = it } }
    }

    /** Model reply → note. Tolerates ```json fences and text around the object. */
    fun parse(raw: String): UsageNote {
        val start = raw.indexOf('{')
        val end = raw.lastIndexOf('}')
        require(start >= 0 && end > start) { "Model không trả về JSON" }
        val o = JSONObject(raw.substring(start, end + 1))
        fun strs(k: String) = o.optJSONArray(k)?.let { a ->
            (0 until a.length()).map { a.optString(it).trim() }.filter { it.isNotEmpty() }
        }.orEmpty()
        val examples = o.optJSONArray("examples")?.let { a ->
            (0 until a.length()).mapNotNull { a.optJSONObject(it) }
                .filter { it.optString("zh").isNotBlank() }
                .map { Triple(it.optString("zh"), it.optString("pinyin"), it.optString("vi")) }
        }.orEmpty()
        val confusables = o.optJSONArray("confusables")?.let { a ->
            (0 until a.length()).mapNotNull { a.optJSONObject(it) }
                .filter { it.optString("word").isNotBlank() }
                .map { it.optString("word") to it.optString("difference") }
        }.orEmpty()
        return UsageNote(o.optString("meaning_here"), o.optString("explanation"), strs("grammar"),
            examples, strs("collocations"), confusables)
    }
}
