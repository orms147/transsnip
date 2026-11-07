package io.github.orms147.transsnip

import android.app.Activity
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Intent
import android.os.Bundle
import android.view.View
import android.view.ViewGroup
import android.speech.tts.TextToSpeech
import android.widget.PopupMenu
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
    private lateinit var copyBtn: TextView
    private lateinit var retryBtn: TextView
    private lateinit var speakBtn: TextView
    private lateinit var meta: TextView
    private var tts: TextToSpeech? = null
    private var started = 0L
    @Volatile private var lastClient: OpenRouterClient? = null
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
        speakBtn = findViewById(R.id.speak)
        meta = findViewById(R.id.meta)
        copyBtn.setOnClickListener { copy() }
        retryBtn.setOnClickListener { start() }
        speakBtn.setOnClickListener { speak() }
        speakBtn.setOnLongClickListener { speak(translationToo = true); true }
        header.setOnClickListener { showLanguageMenu() }
        findViewById<View>(R.id.settings).setOnClickListener {
            startActivity(Intent(this, MainActivity::class.java))
        }
        findViewById<View>(R.id.close).setOnClickListener { finish() }

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
        io.github.orms147.transsnip.screen.ScreenService.ownUi(true)
    }

    override fun onStop() {
        io.github.orms147.transsnip.screen.ScreenService.ownUi(false)
        super.onStop()
    }

    override fun onDestroy() {
        worker.shutdownNow()
        zhWorker.shutdownNow()
        tts?.shutdown()
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
        header.text = getString(R.string.header_lang, "…", Prompts.langName(target).let(::vnName)) + "  ▾"
        if (text.isEmpty()) return showError(getString(R.string.err_no_text))
        if (key.isNullOrBlank()) return showError(getString(R.string.err_no_key))
        showLoading()
        started = System.currentTimeMillis()
        val model = settings.model
        worker.execute {
            // Streamed: the first words show up while the rest is still being generated.
            val client = OpenRouterClient(key, model)
            lastClient = client
            val outcome = runCatching {
                Translator.forModel(client, model).translate(text, target) { partial ->
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
        meta.text = ""
        setActions(false)
    }

    /** Copy / listen / retry only mean something once there is a translation. */
    private fun setActions(enabled: Boolean) {
        // 🔊 reads the original, so it works before the translation arrives.
        for (b in listOf(copyBtn, retryBtn)) {
            b.isEnabled = enabled
            b.alpha = if (enabled) 1f else 0.35f
        }
    }

    private fun showPartial(partial: String) {
        if (partial.isEmpty()) return
        progress.visibility = View.GONE
        resultView.text = partial
        resultView.visibility = View.VISIBLE
    }

    private fun showResult(r: TranslationResult) {
        translation = r.translation
        val src = r.sourceLang?.let { vnName(Prompts.langName(it)) } ?: "?"
        header.text = getString(R.string.header_lang, src, vnName(Prompts.langName(r.targetLang))) + "  ▾"
        progress.visibility = View.GONE
        resultView.text = r.translation
        resultView.visibility = View.VISIBLE
        setActions(true)
        val model = AppSettings.MODELS.firstOrNull { it.second == settings.model }?.first
            ?.substringBefore(" —")?.substringBefore(" (") ?: settings.model.substringAfter('/')
        val total = System.currentTimeMillis() - started
        meta.text = when {
            started == 0L -> model
            // Slow: show which part — network/queue before the model even
            // answered, or the model writing — so it's clear what to change.
            total > SLOW_MS -> getString(R.string.meta_slow, model, total / 1000.0,
                (lastClient?.lastFirstTokenMs ?: 0) / 1000.0, (total - (lastClient?.lastFirstTokenMs ?: 0)) / 1000.0)
            else -> getString(R.string.meta, model, total / 1000.0)
        }
    }

    private fun showError(message: String) {
        progress.visibility = View.GONE
        resultView.visibility = View.GONE
        errorView.text = message
        errorView.visibility = View.VISIBLE
        setActions(false)
        retryBtn.isEnabled = true
        retryBtn.alpha = 1f
    }

    companion object {
        const val EXTRA_TRANSLATION = "io.github.orms147.transsnip.TRANSLATION"
        private const val SLOW_MS = 3000L
    }

    /** Change target language or model right here — and translate again. */
    private fun showLanguageMenu() {
        val menu = PopupMenu(this, header)
        menu.menu.add(0, 0, 0, getString(R.string.menu_target)).isEnabled = false
        AppSettings.TARGETS.forEachIndexed { i, (label, code) ->
            menu.menu.add(1, 100 + i, 1 + i, (if (code == settings.targetLang) "✓  " else "     ") + label)
        }
        menu.menu.add(2, 1, 50, getString(R.string.menu_model)).isEnabled = false
        AppSettings.MODELS.forEachIndexed { i, (label, id) ->
            menu.menu.add(3, 200 + i, 51 + i, (if (id == settings.model) "✓  " else "     ") + label)
        }
        menu.setOnMenuItemClickListener { item ->
            when (item.itemId) {
                in 100 until 200 -> settings.targetLang = AppSettings.TARGETS[item.itemId - 100].second
                in 200 until 300 -> settings.model = AppSettings.MODELS[item.itemId - 200].second
                else -> return@setOnMenuItemClickListener false
            }
            start()
            true
        }
        menu.show()
    }

    /** Read the translation aloud in the target language (system TTS). */
    /**
     * 🔊 reads the ORIGINAL in its own language — hearing how the Chinese (or
     * English…) is pronounced is the point; the translation is already
     * readable. Long-press 🔊 reads the translation instead.
     */
    private fun speak(translationToo: Boolean = false) {
        val (say, lang) = if (translationToo) translation to settings.targetLang
        else text to (LangDetect.detect(text) ?: "en")
        if (say.isEmpty()) return
        val locale = when (lang.substringBefore('-')) {
            "vi" -> java.util.Locale("vi", "VN")
            "zh" -> java.util.Locale.SIMPLIFIED_CHINESE
            "ja" -> java.util.Locale.JAPAN
            "ko" -> java.util.Locale.KOREA
            else -> java.util.Locale.US
        }
        val engine = tts
        if (engine != null) {
            sayWith(engine, locale, say)
            return
        }
        tts = TextToSpeech(this) { status ->
            val t = tts ?: return@TextToSpeech
            if (status == TextToSpeech.SUCCESS) sayWith(t, locale, say)
            else Toast.makeText(this, R.string.no_tts, Toast.LENGTH_LONG).show()
        }
    }

    private fun sayWith(engine: TextToSpeech, locale: java.util.Locale, text: String) {
        val ok = engine.setLanguage(locale)
        if (ok == TextToSpeech.LANG_MISSING_DATA || ok == TextToSpeech.LANG_NOT_SUPPORTED) {
            Toast.makeText(this, R.string.no_tts, Toast.LENGTH_LONG).show()
            return
        }
        engine.speak(text, TextToSpeech.QUEUE_FLUSH, null, "transsnip")
    }

    private fun vnName(english: String) = when (english) {
        "Vietnamese" -> "Việt"
        "English" -> "Anh"
        "Simplified Chinese" -> "Trung"
        "Traditional Chinese" -> "Trung (phồn)"
        "Japanese" -> "Nhật"
        "Korean" -> "Hàn"
        else -> english
    }

    private fun copy() {
        val cm = getSystemService(ClipboardManager::class.java)
        cm.setPrimaryClip(ClipData.newPlainText("TransSnip", translation))
        Toast.makeText(this, R.string.copied, Toast.LENGTH_SHORT).show()
    }
}
