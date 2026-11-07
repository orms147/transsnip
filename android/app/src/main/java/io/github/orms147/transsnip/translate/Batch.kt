package io.github.orms147.transsnip.translate

import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/**
 * Translates many short lines (everything readable on a screen) in ONE request:
 * lines go out numbered "[n] text", come back "[n] translation", and each one
 * is handed to [translate]'s callback as soon as its line finishes streaming.
 * Lines the model dropped or left untranslated get one more try each, in
 * parallel, without holding up the rest.
 */
class BatchTranslator(private val completer: Completer, private val minimalFirst: Boolean = false) {

    /**
     * Output tokens come out one after another, so one request for 18 lines
     * takes ~3 s even though the first line is ready in ~1 s. Splitting the
     * screen into a few chunks sent in parallel brings the total close to a
     * single chunk's time. Chunks follow screen order, top first.
     */
    fun translate(lines: List<String>, target: String, onLine: (Int, String) -> Unit) {
        if (lines.isEmpty()) return
        val parts = minOf(MAX_PARALLEL, (lines.size + CHUNK - 1) / CHUNK)
        if (parts <= 1) return translateChunk(lines, target, onLine)
        val size = (lines.size + parts - 1) / parts
        val lock = Any()
        val pool = Executors.newFixedThreadPool(parts)
        try {
            val jobs = lines.chunked(size).mapIndexed { c, chunk ->
                pool.submit<Throwable?> {
                    runCatching {
                        translateChunk(chunk, target) { i, t -> synchronized(lock) { onLine(c * size + i, t) } }
                    }.exceptionOrNull()
                }
            }
            val errors = jobs.map { it.get() }
            // Only fail when every chunk failed; partial results already went out.
            if (errors.all { it != null }) throw errors.first()!!
        } finally {
            pool.shutdown()
        }
    }

    private fun translateChunk(lines: List<String>, target: String, onLine: (Int, String) -> Unit) {
        val items = lines.map { it.replace('\n', ' ').trim() }
        val done = HashSet<Int>()
        // Model kept the source script (often a name it won't translate):
        // keep its answer as a fallback, but try that line once more on its own.
        val provisional = HashMap<Int, String>()
        fun accept(parsed: Map<Int, String>) {
            for ((i, t) in parsed) {
                if (i in done || i !in items.indices || t.isBlank()) continue
                if (Prompts.looksUntranslated(t, target) && Prompts.needsTranslation(items[i], target)) {
                    provisional[i] = t
                    continue
                }
                done += i
                onLine(i, t)
            }
        }

        val source = LangDetect.detect(items.joinToString("\n"))
        var failure: Exception? = null
        try {
            val raw = if (items.size == 1) {
                completer.stream(Prompts.batchSingleSystem(target, source, minimalFirst), Prompts.userTurn(items[0], target)) {}
                    .let { "[1] " + it.trim().replace('\n', ' ') }
            } else {
                completer.stream(Prompts.batchSystemPrompt(target, source, minimalFirst), Prompts.batchUserTurn(items, target)) { text ->
                    val end = text.lastIndexOf('\n')
                    if (end > 0) accept(parse(text.substring(0, end)))   // only lines that are complete
                }
            }
            accept(parse(raw))
        } catch (e: Exception) {
            failure = e
        }

        val missing = items.indices.filter { it !in done }
        if (missing.isEmpty()) return
        // Nothing usable at all and the request itself failed: report that
        // error rather than firing N more requests that will fail the same way.
        if (missing.size == items.size && failure != null && provisional.isEmpty()) {
            throw failure as? TranslationException ?: TranslationException(failure.message ?: "", failure)
        }
        // One plain request per missing line, all at once. Whatever isn't back
        // within STRAGGLER_MS is delivered later — it doesn't hold up the screen.
        val pool = Executors.newFixedThreadPool(minOf(4, missing.size))
        val jobs = missing.map { i ->
            pool.submit {
                val item = items[i]
                val t = runCatching {
                    completer.complete(Prompts.minimalSystemPrompt(target, LangDetect.detect(item)), Prompts.userTurn(item, target)).trim()
                }.getOrNull()
                val use = when {
                    t.isNullOrEmpty() -> provisional[i]
                    Prompts.looksUntranslated(t, target) -> provisional[i] ?: t
                    else -> t
                }
                if (use != null) synchronized(this) { onLine(i, use) }
            }
        }
        pool.shutdown()
        val deadline = System.currentTimeMillis() + STRAGGLER_MS
        for (j in jobs) {
            val left = deadline - System.currentTimeMillis()
            if (left <= 0) break
            runCatching { j.get(left, TimeUnit.MILLISECONDS) }
        }
    }

    companion object {
        private const val CHUNK = 4          // lines per request before splitting
        private const val MAX_PARALLEL = 5
        private const val STRAGGLER_MS = 1500L
        private val LINE = Regex("""^\s*[\[【(]?(\d{1,3})(?:[\]】)][.:：]?|[.:：])\s?(.*)$""")

        /** "[n] text" lines → 0-based index → text. Unnumbered lines are ignored. */
        fun parse(reply: String): Map<Int, String> {
            val out = LinkedHashMap<Int, String>()
            for (line in reply.lineSequence()) {
                val m = LINE.matchEntire(line.trimEnd()) ?: continue
                val n = m.groupValues[1].toInt() - 1
                val text = m.groupValues[2].trim()
                if (n >= 0 && text.isNotEmpty() && n !in out) out[n] = text
            }
            return out
        }
    }
}
