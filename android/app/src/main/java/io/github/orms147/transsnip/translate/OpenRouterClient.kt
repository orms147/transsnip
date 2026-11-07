package io.github.orms147.transsnip.translate

import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/** OpenRouter chat completions over plain HttpURLConnection (no SDK). */
class OpenRouterClient(private val apiKey: String, private val model: String) : Completer {

    // Cheap models often "think" by default — seconds of hidden, billed output
    // a translation doesn't need. Models that REQUIRE reasoning reject "none":
    // then retry without it and stop sending it.
    private var reasoningOff = true

    override fun complete(system: String, user: String): String = try {
        post(system, user)
    } catch (e: TranslationException) {
        if (!reasoningOff || e.message?.contains("reasoning", ignoreCase = true) != true) throw e
        reasoningOff = false
        post(system, user)
    }

    private fun post(system: String, user: String): String {
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

        val conn = (URL(ENDPOINT).openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            connectTimeout = 15_000
            readTimeout = 60_000
            doOutput = true
            setRequestProperty("Authorization", "Bearer $apiKey")
            setRequestProperty("Content-Type", "application/json")
            setRequestProperty("HTTP-Referer", "https://github.com/orms147/transsnip")
            setRequestProperty("X-Title", "TransSnip Android")
        }
        try {
            conn.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
            val code = conn.responseCode
            val stream = if (code in 200..299) conn.inputStream else conn.errorStream
            val text = stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }.orEmpty()
            if (code !in 200..299) throw TranslationException("OpenRouter $code: ${errorMessage(text)}")
            val json = JSONObject(text)
            json.optJSONObject("error")?.let { throw TranslationException(it.optString("message")) }
            val choices = json.optJSONArray("choices") ?: return ""
            if (choices.length() == 0) return ""
            val message = choices.getJSONObject(0).optJSONObject("message") ?: return ""
            return if (message.isNull("content")) "" else message.optString("content")
        } finally {
            conn.disconnect()
        }
    }

    private fun errorMessage(body: String): String = try {
        JSONObject(body).optJSONObject("error")?.optString("message")?.takeIf { it.isNotEmpty() } ?: body.take(200)
    } catch (_: Exception) {
        body.take(200)
    }

    companion object {
        private const val ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
    }
}
