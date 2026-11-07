package io.github.orms147.transsnip.translate

import org.json.JSONArray
import org.json.JSONObject
import java.io.InputStream
import java.net.HttpURLConnection
import java.net.URL

/**
 * OpenRouter chat completions over plain HttpURLConnection (no SDK).
 *
 * Latency notes: a successful response is read to the end and closed but the
 * connection is NOT disconnect()ed, so Android's global connection pool keeps
 * the TLS session alive and the next request skips the handshake (~200–400 ms
 * on mobile). [warmUp] opens that connection ahead of time.
 */
class OpenRouterClient(private val apiKey: String, private val model: String) : Completer {

    // Cheap models often "think" by default — seconds of hidden, billed output
    // a translation doesn't need. Models that REQUIRE reasoning reject "none":
    // then retry without it and stop sending it.
    private var reasoningOff = true

    override fun complete(system: String, user: String): String =
        withReasoningRetry { request(system, user, null) }

    override fun stream(system: String, user: String, onText: (String) -> Unit): String =
        withReasoningRetry { request(system, user, onText) }

    private fun withReasoningRetry(block: () -> String): String = try {
        block()
    } catch (e: TranslationException) {
        if (!reasoningOff || e.message?.contains("reasoning", ignoreCase = true) != true) throw e
        reasoningOff = false
        block()
    }

    private fun request(system: String, user: String, onText: ((String) -> Unit)?): String {
        val body = JSONObject()
            .put("model", model)
            .put(
                "messages",
                JSONArray()
                    .put(JSONObject().put("role", "system").put("content", system))
                    .put(JSONObject().put("role", "user").put("content", user)),
            )
            .put("max_tokens", 2048)
            .put("temperature", 0.1)
        if (reasoningOff) body.put("reasoning", JSONObject().put("effort", "none"))
        if (onText != null) body.put("stream", true)

        val conn = open(ENDPOINT, apiKey).apply {
            requestMethod = "POST"
            doOutput = true
            setRequestProperty("Content-Type", "application/json")
        }
        try {
            conn.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
            val code = conn.responseCode
            if (code !in 200..299) {
                val text = conn.errorStream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }.orEmpty()
                throw TranslationException("OpenRouter $code: ${errorMessage(text)}")
            }
            return if (onText == null) parseFull(conn.inputStream) else readStream(conn.inputStream, onText)
        } catch (e: Exception) {
            conn.disconnect()   // only on failure — success keeps the pooled connection
            throw if (e is TranslationException) e else TranslationException(e.message ?: e.javaClass.simpleName, e)
        }
    }

    private fun parseFull(input: InputStream): String {
        val json = JSONObject(input.bufferedReader(Charsets.UTF_8).use { it.readText() })
        json.optJSONObject("error")?.let { throw TranslationException(it.optString("message")) }
        val message = json.optJSONArray("choices")?.optJSONObject(0)?.optJSONObject("message") ?: return ""
        return if (message.isNull("content")) "" else message.optString("content")
    }

    /** Server-sent events: "data: {chunk}" lines, ": comment" keep-alives, "data: [DONE]". */
    private fun readStream(input: InputStream, onText: (String) -> Unit): String {
        val sb = StringBuilder()
        input.bufferedReader(Charsets.UTF_8).use { r ->
            while (true) {
                val line = r.readLine() ?: break   // read to EOF so the connection can be reused
                if (!line.startsWith("data:")) continue
                val data = line.substring(5).trim()
                if (data == "[DONE]" || data.isEmpty()) continue
                val json = try { JSONObject(data) } catch (_: Exception) { continue }
                json.optJSONObject("error")?.let { throw TranslationException(it.optString("message")) }
                val delta = json.optJSONArray("choices")?.optJSONObject(0)?.optJSONObject("delta") ?: continue
                if (delta.isNull("content")) continue
                val piece = delta.optString("content")
                if (piece.isEmpty()) continue
                sb.append(piece)
                onText(sb.toString())
            }
        }
        return sb.toString()
    }

    private fun errorMessage(body: String): String = try {
        JSONObject(body).optJSONObject("error")?.optString("message")?.takeIf { it.isNotEmpty() } ?: body.take(200)
    } catch (_: Exception) {
        body.take(200)
    }

    companion object {
        private const val ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
        private const val KEY_INFO = "https://openrouter.ai/api/v1/key"

        private fun open(url: String, apiKey: String) =
            (URL(url).openConnection() as HttpURLConnection).apply {
                connectTimeout = 15_000
                readTimeout = 60_000
                setRequestProperty("Authorization", "Bearer $apiKey")
                setRequestProperty("HTTP-Referer", "https://github.com/orms147/transsnip")
                setRequestProperty("X-Title", "TransSnip Android")
            }

        /**
         * Tiny authenticated GET so DNS + TCP + TLS are done before the user
         * asks for a translation; the pooled connection is reused by the POST.
         * [connections] in parallel: a screen goes out as several parallel
         * requests, each needing its own pooled connection.
         * Blocking — call off the main thread. Errors are ignored.
         */
        fun warmUp(apiKey: String, connections: Int = 1) {
            val threads = (1..connections).map {
                Thread {
                    try {
                        open(KEY_INFO, apiKey).inputStream.use { it.readBytes() }
                    } catch (_: Exception) {
                    }
                }.apply { start() }
            }
            threads.forEach { it.join() }
        }
    }
}
