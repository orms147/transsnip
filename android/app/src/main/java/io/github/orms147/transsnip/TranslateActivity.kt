package io.github.orms147.transsnip

import android.app.Activity
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Intent
import android.os.Bundle
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.ProgressBar
import android.widget.TextView
import android.widget.Toast
import io.github.orms147.transsnip.translate.OpenRouterClient
import io.github.orms147.transsnip.translate.Prompts
import io.github.orms147.transsnip.translate.TranslationResult
import io.github.orms147.transsnip.translate.Translator
import java.util.concurrent.Executors

/**
 * Popup card opened from the text-selection menu ("TransSnip" next to
 * Copy / Share — ACTION_PROCESS_TEXT) or from Share → TransSnip. The selected
 * text arrives verbatim, so there's no OCR error to translate around.
 */
class TranslateActivity : Activity() {

    private val worker = Executors.newSingleThreadExecutor()
    private lateinit var settings: AppSettings
    private lateinit var header: TextView
    private lateinit var sourceView: TextView
    private lateinit var progress: ProgressBar
    private lateinit var resultView: TextView
    private lateinit var errorView: TextView
    private lateinit var copyBtn: Button
    private lateinit var retryBtn: Button
    private var text = ""
    private var translation = ""

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_translate)
        window.setLayout((resources.displayMetrics.widthPixels * 0.92).toInt(),
            ViewGroup.LayoutParams.WRAP_CONTENT)
        settings = AppSettings(this)
        header = findViewById(R.id.header)
        sourceView = findViewById(R.id.source)
        progress = findViewById(R.id.progress)
        resultView = findViewById(R.id.result)
        errorView = findViewById(R.id.error)
        copyBtn = findViewById(R.id.copy)
        retryBtn = findViewById(R.id.retry)
        copyBtn.setOnClickListener { copy() }
        retryBtn.setOnClickListener { start() }
        findViewById<Button>(R.id.settings).setOnClickListener {
            startActivity(Intent(this, MainActivity::class.java))
        }
        findViewById<Button>(R.id.close).setOnClickListener { finish() }

        text = selectedText(intent)
        sourceView.text = text
        start()
    }

    override fun onDestroy() {
        worker.shutdownNow()
        super.onDestroy()
    }

    private fun selectedText(intent: Intent): String =
        (intent.getCharSequenceExtra(Intent.EXTRA_PROCESS_TEXT)
            ?: intent.getCharSequenceExtra(Intent.EXTRA_TEXT))?.toString()?.trim().orEmpty()

    private fun start() {
        val key = settings.apiKey
        val target = settings.targetLang
        header.text = getString(R.string.header_lang, "…", target.uppercase())
        if (text.isEmpty()) return showError(getString(R.string.err_no_text))
        if (key.isNullOrBlank()) return showError(getString(R.string.err_no_key))
        showLoading()
        val model = settings.model
        worker.execute {
            val outcome = runCatching { Translator(OpenRouterClient(key, model)).translate(text, target) }
            runOnUiThread {
                if (isDestroyed) return@runOnUiThread
                outcome.fold(::showResult) { showError(it.message ?: it.toString()) }
            }
        }
    }

    private fun showLoading() {
        progress.visibility = View.VISIBLE
        resultView.visibility = View.GONE
        errorView.visibility = View.GONE
        retryBtn.visibility = View.GONE
        copyBtn.isEnabled = false
    }

    private fun showResult(r: TranslationResult) {
        translation = r.translation
        val src = r.sourceLang?.let { Prompts.langName(it) } ?: "?"
        header.text = getString(R.string.header_lang, src, Prompts.langName(r.targetLang))
        progress.visibility = View.GONE
        resultView.text = r.translation
        resultView.visibility = View.VISIBLE
        copyBtn.isEnabled = true
    }

    private fun showError(message: String) {
        progress.visibility = View.GONE
        resultView.visibility = View.GONE
        errorView.text = message
        errorView.visibility = View.VISIBLE
        retryBtn.visibility = View.VISIBLE
        copyBtn.isEnabled = false
    }

    private fun copy() {
        val cm = getSystemService(ClipboardManager::class.java)
        cm.setPrimaryClip(ClipData.newPlainText("TransSnip", translation))
        Toast.makeText(this, R.string.copied, Toast.LENGTH_SHORT).show()
    }
}
