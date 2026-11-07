package io.github.orms147.transsnip

import android.app.Activity
import android.os.Bundle
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.EditText
import android.widget.Spinner
import android.widget.TextView
import io.github.orms147.transsnip.translate.OpenRouterClient
import io.github.orms147.transsnip.translate.Translator
import java.util.concurrent.Executors

/** Settings: OpenRouter key, model, target language, and a test translation. */
class MainActivity : Activity() {

    private val worker = Executors.newSingleThreadExecutor()
    private lateinit var settings: AppSettings
    private lateinit var keyInput: EditText
    private lateinit var modelSpinner: Spinner
    private lateinit var targetSpinner: Spinner
    private lateinit var status: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        settings = AppSettings(this)
        keyInput = findViewById(R.id.api_key)
        modelSpinner = findViewById(R.id.model)
        targetSpinner = findViewById(R.id.target)
        status = findViewById(R.id.status)

        // Debug builds only: a key piped into files/debug_api_key (adb exec-in
        // run-as … — stdin, so it never shows up on a command line or in
        // logcat) is moved into the Keystore-encrypted setting and deleted.
        if (BuildConfig.DEBUG) {
            val f = java.io.File(filesDir, "debug_api_key")
            if (f.exists()) {
                f.readText().trim().takeIf { it.isNotEmpty() }?.let { settings.apiKey = it }
                f.delete()
            }
        }

        modelSpinner.adapter = adapter(AppSettings.MODELS.map { it.first })
        modelSpinner.setSelection(AppSettings.MODELS.indexOfFirst { it.second == settings.model }.coerceAtLeast(0))
        targetSpinner.adapter = adapter(AppSettings.TARGETS.map { it.first })
        targetSpinner.setSelection(AppSettings.TARGETS.indexOfFirst { it.second == settings.targetLang }.coerceAtLeast(0))
        if (!settings.apiKey.isNullOrBlank()) keyInput.hint = getString(R.string.key_saved_hint)

        findViewById<Button>(R.id.save).setOnClickListener { save() }
        findViewById<Button>(R.id.test).setOnClickListener { test() }
    }

    override fun onDestroy() {
        worker.shutdownNow()
        super.onDestroy()
    }

    private fun adapter(items: List<String>) =
        ArrayAdapter(this, android.R.layout.simple_spinner_item, items).apply {
            setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item)
        }

    private fun save() {
        keyInput.text.toString().takeIf { it.isNotBlank() }?.let { settings.apiKey = it }
        settings.model = AppSettings.MODELS[modelSpinner.selectedItemPosition].second
        settings.targetLang = AppSettings.TARGETS[targetSpinner.selectedItemPosition].second
        keyInput.text.clear()
        if (!settings.apiKey.isNullOrBlank()) keyInput.hint = getString(R.string.key_saved_hint)
        status.setText(R.string.saved)
    }

    private fun test() {
        save()
        val key = settings.apiKey
        if (key.isNullOrBlank()) {
            status.setText(R.string.err_no_key)
            return
        }
        status.setText(R.string.testing)
        val model = settings.model
        val target = settings.targetLang
        val started = System.currentTimeMillis()
        worker.execute {
            val outcome = runCatching { Translator(OpenRouterClient(key, model)).translate(SAMPLE, target) }
            val ms = System.currentTimeMillis() - started
            runOnUiThread {
                if (isDestroyed) return@runOnUiThread
                status.text = outcome.fold(
                    { "$SAMPLE\n→ ${it.translation}\n(${ms} ms)" },
                    { getString(R.string.test_failed, it.message) },
                )
            }
        }
    }

    companion object {
        // The sentence hy-mt2 used to answer with an empty reply (needs the fallback).
        private const val SAMPLE = "让你唱歌爆炸好听"
    }
}
