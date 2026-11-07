package io.github.orms147.transsnip

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** Model / target language prefs + the OpenRouter key, encrypted at rest. */
class AppSettings(context: Context) {
    private val prefs = context.getSharedPreferences("settings", Context.MODE_PRIVATE)

    var model: String
        get() = prefs.getString("model", DEFAULT_MODEL) ?: DEFAULT_MODEL
        set(value) = prefs.edit().putString("model", value).apply()

    var targetLang: String
        get() = prefs.getString("target", "vi") ?: "vi"
        set(value) = prefs.edit().putString("target", value).apply()

    /** Chinese study aids in the popup: pinyin, Hán-Việt, tap a word → word card. */
    var zhStudy: Boolean
        get() = prefs.getBoolean("zh_study", true)
        set(value) = prefs.edit().putBoolean("zh_study", value).apply()

    /** Floating bubble (screen translation) while the accessibility service is on. */
    var bubble: Boolean
        get() = prefs.getBoolean(KEY_BUBBLE, true)
        set(value) = prefs.edit().putBoolean(KEY_BUBBLE, value).apply()

    var bubbleX: Int
        get() = prefs.getInt("bubble_x", -1)
        set(value) = prefs.edit().putInt("bubble_x", value).apply()

    var bubbleY: Int
        get() = prefs.getInt("bubble_y", -1)
        set(value) = prefs.edit().putInt("bubble_y", value).apply()

    var menuHintShown: Boolean
        get() = prefs.getBoolean("menu_hint", false)
        set(value) = prefs.edit().putBoolean("menu_hint", value).apply()

    var hintsShown: Int
        get() = prefs.getInt("hints_live", 0)
        set(value) = prefs.edit().putInt("hints_live", value).apply()

    fun onChange(listener: android.content.SharedPreferences.OnSharedPreferenceChangeListener) =
        prefs.registerOnSharedPreferenceChangeListener(listener)

    fun offChange(listener: android.content.SharedPreferences.OnSharedPreferenceChangeListener) =
        prefs.unregisterOnSharedPreferenceChangeListener(listener)

    /** AES-GCM with a non-exportable key in the Android Keystore. */
    var apiKey: String?
        get() {
            val stored = prefs.getString("api_key", null) ?: return null
            return try {
                val (iv, data) = stored.split(":").map { Base64.decode(it, Base64.NO_WRAP) }
                val cipher = Cipher.getInstance(TRANSFORM)
                cipher.init(Cipher.DECRYPT_MODE, secretKey(), GCMParameterSpec(128, iv))
                String(cipher.doFinal(data), Charsets.UTF_8)
            } catch (_: Exception) {
                null
            }
        }
        set(value) {
            if (value.isNullOrBlank()) {
                prefs.edit().remove("api_key").apply()
                return
            }
            val cipher = Cipher.getInstance(TRANSFORM)
            cipher.init(Cipher.ENCRYPT_MODE, secretKey())
            val data = cipher.doFinal(value.trim().toByteArray(Charsets.UTF_8))
            val enc = Base64.encodeToString(cipher.iv, Base64.NO_WRAP) + ":" +
                Base64.encodeToString(data, Base64.NO_WRAP)
            prefs.edit().putString("api_key", enc).apply()
        }

    private fun secretKey(): SecretKey {
        val ks = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (ks.getEntry(KEY_ALIAS, null) as? KeyStore.SecretKeyEntry)?.let { return it.secretKey }
        val gen = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        gen.init(
            KeyGenParameterSpec.Builder(
                KEY_ALIAS,
                KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
            )
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .build(),
        )
        return gen.generateKey()
    }

    companion object {
        const val KEY_BUBBLE = "bubble"
        const val DEFAULT_MODEL = "tencent/hy-mt2-30b-a3b"
        private const val KEY_ALIAS = "transsnip_api_key"
        private const val TRANSFORM = "AES/GCM/NoPadding"

        // Same list as the desktop app; latency/cost measured there on zh→vi lines.
        val MODELS = listOf(
            "Hy-MT2 30B — nhanh nhất (0.7s, \$0.05/1k câu)" to "tencent/hy-mt2-30b-a3b",
            "Gemini 2.5 Flash-Lite (1.0s, \$0.07/1k câu)" to "google/gemini-2.5-flash-lite",
            "DeepSeek V4.1 Flash (1.3s, \$0.11/1k câu)" to "deepseek/deepseek-v4.1-flash",
            "Qwen3.7 Flash — rẻ nhất (1.4s, \$0.02/1k câu)" to "qwen/qwen3.7-flash",
            "Gemini 3.6 Flash" to "google/gemini-3.6-flash",
            "Claude Haiku 5.5" to "anthropic/claude-haiku-5.5",
            "Gemma 4 31B (miễn phí)" to "google/gemma-4-31b-it:free",
        )

        val TARGETS = listOf(
            "Tiếng Việt" to "vi",
            "English" to "en",
            "中文 (简体)" to "zh-Hans",
        )
    }
}
