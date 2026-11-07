package io.github.orms147.transsnip.translate

/** One chat-completion call: system + user message → reply text ("" if none). */
fun interface Completer {
    fun complete(system: String, user: String): String

    /** Same call, streamed: [onText] gets the reply accumulated so far. */
    fun stream(system: String, user: String, onText: (String) -> Unit): String =
        complete(system, user).also { if (it.isNotEmpty()) onText(it) }
}

class TranslationException(message: String, cause: Throwable? = null) : Exception(message, cause)

data class TranslationResult(
    val source: String,
    val sourceLang: String?,
    val targetLang: String,
    val translation: String,
)

/**
 * Same recovery steps as the desktop LLMTranslator (transsnip/translate/llm.py):
 * empty reply → retry once with the other prompt; reply still in the source
 * script → retry once and keep whichever answer is actually translated.
 *
 * [minimalFirst]: start with the bare prompt. Hy-MT2 answers the full prompt
 * with an empty reply often enough that leading with it costs a whole extra
 * round trip — see [forModel].
 */
class Translator(private val completer: Completer, private val minimalFirst: Boolean = false) {

    fun translate(text: String, target: String, onPartial: ((String) -> Unit)? = null): TranslationResult {
        val source = LangDetect.detect(text)
        val user = Prompts.userTurn(text, target)
        val full = Prompts.systemPrompt(target, source)
        val minimal = Prompts.minimalSystemPrompt(target, source)
        val first = if (minimalFirst) minimal else full
        var raw = call(first, user, onPartial)
        if (raw.isEmpty()) {
            raw = call(if (minimalFirst) full else minimal, user, onPartial)
        }
        if (raw.isNotEmpty() && Prompts.looksUntranslated(raw, target)) {
            val retry = call(first, user, null)
            if (retry.isNotEmpty() && !Prompts.looksUntranslated(retry, target)) raw = retry
        }
        if (raw.isEmpty()) throw TranslationException("Model không trả về bản dịch — thử model khác.")
        return TranslationResult(text, source, target, raw)
    }

    private fun call(system: String, user: String, onPartial: ((String) -> Unit)?): String = try {
        if (onPartial == null) completer.complete(system, user).trim()
        else completer.stream(system, user) { onPartial(it.trim()) }.trim()
    } catch (e: TranslationException) {
        throw e
    } catch (e: Exception) {
        throw TranslationException(e.message ?: e.javaClass.simpleName, e)
    }

    companion object {
        fun minimalFirst(model: String) = model.startsWith("tencent/hy-mt")
        fun forModel(completer: Completer, model: String) = Translator(completer, minimalFirst(model))
    }
}
