package io.github.orms147.transsnip.translate

/** One chat-completion call: system + user message → reply text ("" if none). */
fun interface Completer {
    fun complete(system: String, user: String): String
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
 * empty reply → retry once with the minimal prompt; reply still in the source
 * script → retry once and keep whichever answer is actually translated.
 */
class Translator(private val completer: Completer) {

    fun translate(text: String, target: String): TranslationResult {
        val source = LangDetect.detect(text)
        val user = Prompts.userTurn(text, target)
        val system = Prompts.systemPrompt(target, source)
        var raw = call(system, user)
        if (raw.isEmpty()) {
            raw = call(Prompts.minimalSystemPrompt(target, source), user)
        }
        if (raw.isNotEmpty() && Prompts.looksUntranslated(raw, target)) {
            val retry = call(system, user)
            if (retry.isNotEmpty() && !Prompts.looksUntranslated(retry, target)) raw = retry
        }
        if (raw.isEmpty()) throw TranslationException("Model không trả về bản dịch — thử model khác.")
        return TranslationResult(text, source, target, raw)
    }

    private fun call(system: String, user: String): String = try {
        completer.complete(system, user).trim()
    } catch (e: TranslationException) {
        throw e
    } catch (e: Exception) {
        throw TranslationException(e.message ?: e.javaClass.simpleName, e)
    }
}
