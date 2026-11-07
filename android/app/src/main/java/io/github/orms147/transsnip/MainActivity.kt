package io.github.orms147.transsnip

import android.app.Activity
import android.os.Build
import android.view.View
import android.widget.AdapterView
import android.widget.Toast
import android.content.ComponentName
import android.content.Intent
import android.provider.Settings
import android.os.Bundle
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.EditText
import android.widget.Spinner
import android.widget.Switch
import android.widget.TextView
import io.github.orms147.transsnip.screen.ScreenService
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
        keyInput.typeface = android.graphics.Typeface.DEFAULT   // password fields default to monospace
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

        findViewById<Switch>(R.id.zh_study).apply {
            isChecked = settings.zhStudy
            setOnCheckedChangeListener { _, on -> settings.zhStudy = on }
        }
        findViewById<Switch>(R.id.bubble).apply {
            isChecked = settings.bubble
            setOnCheckedChangeListener { _, on -> settings.bubble = on }
        }
        // Spinners save as soon as something is picked — no Save button to forget.
        modelSpinner.adapter = adapter(AppSettings.MODELS.map { it.first })
        modelSpinner.setSelection(AppSettings.MODELS.indexOfFirst { it.second == settings.model }.coerceAtLeast(0))
        modelSpinner.onItemSelectedListener = onPick { settings.model = AppSettings.MODELS[it].second }
        targetSpinner.adapter = adapter(AppSettings.TARGETS.map { it.first })
        targetSpinner.setSelection(AppSettings.TARGETS.indexOfFirst { it.second == settings.targetLang }.coerceAtLeast(0))
        targetSpinner.onItemSelectedListener = onPick { settings.targetLang = AppSettings.TARGETS[it].second }

        findViewById<Button>(R.id.save).setOnClickListener { saveKey() }
        findViewById<Button>(R.id.test).setOnClickListener { test() }
        findViewById<Button>(R.id.screen_settings).setOnClickListener { openAccessibility() }
    }

    override fun onResume() {
        super.onResume()
        refreshSteps()
    }

    override fun onDestroy() {
        worker.shutdownNow()
        super.onDestroy()
    }

    /** Each step shows ✓ once done; hints for a finished step get out of the way. */
    private fun refreshSteps() {
        val hasKey = !settings.apiKey.isNullOrBlank()
        val screenOn = screenServiceOn()
        mark(R.id.step_key, R.string.step_key, hasKey)
        mark(R.id.step_screen, R.string.step_screen, screenOn)
        keyInput.hint = getString(if (hasKey) R.string.key_saved_hint else R.string.api_key_hint)
        findViewById<View>(R.id.key_help).visibility = if (hasKey) View.GONE else View.VISIBLE
        findViewById<Button>(R.id.screen_settings).setText(if (screenOn) R.string.screen_open_settings else R.string.screen_enable)
        findViewById<View>(R.id.screen_restricted).visibility = if (screenOn) View.GONE else View.VISIBLE
    }

    private fun mark(id: Int, label: Int, done: Boolean) {
        findViewById<TextView>(id).apply {
            text = if (done) getString(R.string.step_done, getString(label)) else getString(label)
            setTextColor(if (done) getColor(R.color.ok) else currentTextColorDefault())
        }
    }

    private fun TextView.currentTextColorDefault(): Int {
        val a = obtainStyledAttributes(intArrayOf(android.R.attr.textColorPrimary))
        return a.getColor(0, currentTextColor).also { a.recycle() }
    }

    /** Straight to TransSnip's own switch where the system allows it (Android 12+). */
    private fun openAccessibility() {
        val me = ComponentName(this, ScreenService::class.java).flattenToString()
        val details = Intent("android.settings.ACCESSIBILITY_DETAILS_SETTINGS")
            .putExtra(Intent.EXTRA_COMPONENT_NAME, me)
        val opened = Build.VERSION.SDK_INT >= 31 && runCatching { startActivity(details) }.isSuccess
        if (!opened) startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
    }

    private fun screenServiceOn(): Boolean {
        val enabled = Settings.Secure.getString(contentResolver, Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES).orEmpty()
        val me = ComponentName(this, ScreenService::class.java)
        return enabled.split(':').any { ComponentName.unflattenFromString(it) == me }
    }

    private fun adapter(items: List<String>) =
        ArrayAdapter(this, android.R.layout.simple_spinner_item, items).apply {
            setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item)
        }

    private fun onPick(save: (Int) -> Unit) = object : AdapterView.OnItemSelectedListener {
        override fun onItemSelected(parent: AdapterView<*>?, view: View?, position: Int, id: Long) = save(position)
        override fun onNothingSelected(parent: AdapterView<*>?) {}
    }

    private fun saveKey() {
        keyInput.text.toString().takeIf { it.isNotBlank() }?.let { settings.apiKey = it }
        keyInput.text.clear()
        refreshSteps()
        Toast.makeText(this, R.string.saved, Toast.LENGTH_SHORT).show()
    }

    private fun test() {
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
            val outcome = runCatching { Translator.forModel(OpenRouterClient(key, model), model).translate(SAMPLE, target) }
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
