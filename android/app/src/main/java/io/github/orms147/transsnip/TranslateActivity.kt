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
import android.widget.FrameLayout
import io.github.orms147.transsnip.translate.LangDetect
import io.github.orms147.transsnip.translate.OpenRouterClient
import io.github.orms147.transsnip.translate.Prompts
import io.github.orms147.transsnip.translate.TranslationResult
import io.github.orms147.transsnip.translate.Translator
import io.github.orms147.transsnip.zh.ChineseText
import io.github.orms147.transsnip.zh.ChineseView
import io.github.orms147.transsnip.zh.ZhDict
import java.util.concurrent.Executors

/**
 * Popup card opened from the text-selection menu ("TransSnip" next to
 * Copy / Share — ACTION_PROCESS_TEXT) or from Share → TransSnip. The selected
 * text arrives verbatim, so there's no OCR error to translate around.
 */
class TranslateActivity : Activity() {

    private val worker = Executors.newSingleThreadExecutor()
    private val zhWorker = Executors.newSingleThreadExecutor()   // dictionary work runs beside the API call
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
        if (settings.zhStudy && LangDetect.detect(text) == "zh-Hans") showChinese()
        // Opened from the screen overlay: that line is already translated.
        val ready = intent.getStringExtra(EXTRA_TRANSLATION).orEmpty()
        if (ready.isNotBlank()) {
            showResult(TranslationResult(text, LangDetect.detect(text), settings.targetLang, ready))
        } else {
            start()
        }
    }

    override fun onStart() {
        super.onStart()
        io.github.orms147.transsnip.screen.ScreenService.instance?.ownUi(true)
    }

    override fun onStop() {
        io.github.orms147.transsnip.screen.ScreenService.instance?.ownUi(false)
        super.onStop()
    }

    override fun onDestroy() {
        worker.shutdownNow()
        zhWorker.shutdownNow()
        super.onDestroy()
    }

    /** Pinyin + Hán-Việt for each word in place of the plain source line. */
    private fun showChinese() {
        val src = text
        zhWorker.execute {
            val dict = ZhDict.get(this) ?: return@execute
            val tokens = dict.tokenize(src)
            val data = ChineseText(src, tokens, tokens.map { if (it.isWord) dict.tokenHanviet(it) else "" },
                dict.sentenceHanviet(tokens))
            runOnUiThread {
                if (isDestroyed) return@runOnUiThread
                val view = ChineseView(this).apply {
                    bind(data)
                    onWord = { w, a, b -> openWord(w, a, b) }
                }
                findViewById<FrameLayout>(R.id.zh_container).apply {
                    removeAllViews()
                    addView(view)
                    visibility = View.VISIBLE
                }
                sourceView.visibility = View.GONE
            }
        }
    }

    private fun openWord(word: String, start: Int, end: Int) {
        val sentence = ZhDict.sentenceAt(text, start, end)
        startActivity(Intent(this, WordCardActivity::class.java)
            .putExtra(WordCardActivity.EXTRA_WORD, word)
            .putExtra(WordCardActivity.EXTRA_SENTENCE, sentence)
            // The translation belongs to the whole text; only show it when the
            // text IS that one sentence.
            .putExtra(WordCardActivity.EXTRA_TRANSLATION, if (sentence == text.trim()) translation else ""))
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
            // Streamed: the first words show up while the rest is still being generated.
            val outcome = runCatching {
                Translator.forModel(OpenRouterClient(key, model), model).translate(text, target) { partial ->
                    runOnUiThread { if (!isDestroyed) showPartial(partial) }
                }
            }
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

    private fun showPartial(partial: String) {
        if (partial.isEmpty()) return
        progress.visibility = View.GONE
        resultView.text = partial
        resultView.visibility = View.VISIBLE
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

    companion object {
        const val EXTRA_TRANSLATION = "io.github.orms147.transsnip.TRANSLATION"
    }

    private fun copy() {
        val cm = getSystemService(ClipboardManager::class.java)
        cm.setPrimaryClip(ClipData.newPlainText("TransSnip", translation))
        Toast.makeText(this, R.string.copied, Toast.LENGTH_SHORT).show()
    }
}
