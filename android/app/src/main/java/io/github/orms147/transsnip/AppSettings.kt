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
        // A model dropped from the list (older install) falls back to the default.
        get() = prefs.getString("model", null)?.takeIf { m -> MODELS.any { it.second == m } } ?: DEFAULT_MODEL
        set(value) = prefs.edit().putString("model", value).apply()

    var targetLang: String
        get() = prefs.getString("target", "vi") ?: "vi"
        set(value) = prefs.edit().putString("target", value).apply()

    /** Chinese study aids in the popup: pinyin, Hán-Việt, tap a word → word card. */
    /** Tap on the bubble = translate one still frame (no auto-refresh) instead of following the screen. */
    var frozenDefault: Boolean
        get() = prefs.getBoolean("frozen_default", false)
        set(value) = prefs.edit().putBoolean("frozen_default", value).apply()

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
        const val DEFAULT_MODEL = "deepseek/deepseek-v4.1-flash-1017"
        private const val KEY_ALIAS = "transsnip_api_key"
        private const val TRANSFORM = "AES/GCM/NoPadding"

        // Measured 2026-11-07 via OpenRouter (median: first sentence / 20-line screen).
        val MODELS = listOf(
            "DeepSeek V4.1 Flash 1017 — câu nhanh nhất (0.65s)" to "deepseek/deepseek-v4.1-flash-1017",
            "Hy-MT2 30B — chuyên dịch (0.9s)" to "tencent/hy-mt2-30b-a3b",
            "Gemini 2.5 Flash-Lite — cả màn hình nhanh nhất (1.6s)" to "google/gemini-2.5-flash-lite",
        )

        val TARGETS = listOf(
            "Tiếng Việt" to "vi",
            "English" to "en",
            "中文 (简体)" to "zh-Hans",
        )
    }
}
