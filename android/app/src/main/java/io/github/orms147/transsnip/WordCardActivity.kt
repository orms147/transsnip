package io.github.orms147.transsnip

import android.app.Activity
import android.graphics.Color
import android.graphics.Typeface
import android.os.Bundle
import android.speech.tts.TextToSpeech
import android.text.SpannableString
import android.text.SpannableStringBuilder
import android.text.Spanned
import android.text.style.ForegroundColorSpan
import android.text.style.RelativeSizeSpan
import android.text.style.StyleSpan
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import io.github.orms147.transsnip.translate.OpenRouterClient
import io.github.orms147.transsnip.zh.CharInfo
import io.github.orms147.transsnip.zh.DictEntry
import io.github.orms147.transsnip.zh.Pinyin
import io.github.orms147.transsnip.zh.Token
import io.github.orms147.transsnip.zh.Usage
import io.github.orms147.transsnip.zh.UsageNote
import io.github.orms147.transsnip.zh.ZhDict
import java.util.Locale
import java.util.concurrent.Executors

/**
 * Word card (desktop: ui/word_card.py): characters + tone-coloured pinyin,
 * Hán-Việt, HSK, meanings, the sentence it came from, each character's
 * reading / radical / components, and AI usage notes on demand.
 */
class WordCardActivity : Activity() {

    private val worker = Executors.newSingleThreadExecutor()
    private lateinit var body: LinearLayout
    private var tts: TextToSpeech? = null
    private var ttsReady = false
    private lateinit var word: String
    private lateinit var sentence: String

    private class Data(val token: Token, val hanviet: String, val hsk: Int?,
                       val entries: List<DictEntry>, val chars: List<CharInfo>)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        word = intent.getStringExtra(EXTRA_WORD).orEmpty()
        sentence = intent.getStringExtra(EXTRA_SENTENCE).orEmpty()
        val translation = intent.getStringExtra(EXTRA_TRANSLATION).orEmpty()
        body = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(22), dp(18), dp(22), dp(18))
        }
        setContentView(ScrollView(this).apply { addView(body) })
        // Height follows the content (the dialog window still stops at the screen).
        window.setLayout((resources.displayMetrics.widthPixels * 0.94).toInt(),
            ViewGroup.LayoutParams.WRAP_CONTENT)
        body.addView(ProgressBar(this))
        tts = TextToSpeech(this) { status ->
            ttsReady = status == TextToSpeech.SUCCESS &&
                tts?.setLanguage(Locale.SIMPLIFIED_CHINESE)?.let { it >= 0 } == true
        }
        worker.execute {
            val dict = ZhDict.get(this)
            val data = dict?.let { d ->
                val token = d.annotate(word)
                Data(token, d.tokenHanviet(token), d.hsk(word),
                    d.lookup(word, token.syllables.joinToString(" ") { it.numbered }),
                    token.syllables.filter { it.tone != 0 }.map { d.charInfo(it) })
            }
            runOnUiThread { if (!isDestroyed) render(data, translation) }
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
        tts?.shutdown()
        super.onDestroy()
    }

    private fun render(d: Data?, translation: String) {
        body.removeAllViews()
        if (d == null) {
            body.addView(text("Thiếu dữ liệu tiếng Trung trong bản cài này.", 15f))
            return
        }
        // Header: characters, pinyin, Hán-Việt, HSK + speak.
        val head = LinearLayout(this).apply { gravity = Gravity.CENTER_VERTICAL }
        val col = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        col.addView(text(toned(word, d.token, spaced = false), 40f))
        col.addView(text(toned(d.token.pinyin, d.token, spaced = true), 18f))
        col.addView(text(label("Hán-Việt: ", d.hanviet.uppercase(Locale("vi"))), 15f))
        head.addView(col, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        val side = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; gravity = Gravity.END }
        side.addView(TextView(this, null, 0, R.style.ActionButton).apply {
            text = "🔊 Nghe"
            minHeight = dp(40)
            setOnClickListener { speak() }
        })
        d.hsk?.let { side.addView(text(if (it >= 7) "HSK 7-9" else "HSK $it", 13f).apply {
            setTextColor(ACCENT)
            gravity = Gravity.END
        }) }
        head.addView(side)
        body.addView(head)

        section("Nghĩa")
        val meanings = d.entries.firstOrNull()?.meanings.orEmpty().take(5)
        body.addView(text(
            if (meanings.isEmpty()) "Không có trong từ điển offline — thử “Giải thích cách dùng”."
            else meanings.mapIndexed { i, m -> "${i + 1}. $m" }.joinToString("\n"), 16f))

        if (sentence.isNotEmpty() && sentence != word) {
            section("Trong câu")
            val s = SpannableString(sentence)
            var i = sentence.indexOf(word)
            while (i >= 0) {
                s.setSpan(ForegroundColorSpan(ACCENT), i, i + word.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
                s.setSpan(StyleSpan(Typeface.BOLD), i, i + word.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
                i = sentence.indexOf(word, i + word.length)
            }
            body.addView(text(s, 17f))
            if (translation.isNotEmpty()) body.addView(text(translation, 14f).apply { alpha = 0.65f })
        }

        if (d.chars.size > 1 || d.chars.firstOrNull()?.components?.isNotEmpty() == true) {
            section("Từng chữ")
            d.chars.forEach { body.addView(charRow(it)) }
        }

        section("Cách dùng (AI)")
        val usageBox = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        val btn = TextView(this, null, 0, R.style.ActionButton).apply {
            text = "✨ Giải thích cách dùng + câu ví dụ"
            background = getDrawable(R.drawable.bg_chip)
            setPadding(dp(14), dp(10), dp(14), dp(10))
        }
        btn.setOnClickListener { explain(usageBox, btn) }
        usageBox.addView(btn)
        body.addView(usageBox)
    }

    private fun charRow(c: CharInfo): View {
        val row = LinearLayout(this).apply {
            gravity = Gravity.TOP
            // Baseline alignment pushed the info column down to the big
            // character's baseline and clipped its last lines.
            isBaselineAligned = false
            setPadding(0, dp(6), 0, dp(6))
        }
        row.addView(text(c.char.toString(), 34f).apply { setPadding(0, 0, dp(14), 0) })
        val info = SpannableStringBuilder()
        info.append(c.hanviet.uppercase(Locale("vi")), StyleSpan(Typeface.BOLD), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
        val others = c.hanvietAll.split(',').map { it.trim() }.filter { it.isNotEmpty() && it != c.hanviet }
        if (others.isNotEmpty()) info.append(" (${others.joinToString(", ")})")
        if (c.radical.isNotEmpty()) info.append(" · bộ ${c.radical}")
        if (c.components.size > 1) info.append(" · ${c.components.joinToString(" + ")}")
        if (c.meanings.isNotEmpty()) info.append("\n${c.meanings.take(3).joinToString("; ")}")
        ETYM[c.etymType]?.let { type ->
            val start = info.length
            info.append("\n$type${if (c.etymHint.isNotEmpty()) ": ${c.etymHint}" else ""}")
            info.setSpan(ForegroundColorSpan(Color.GRAY), start, info.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
            info.setSpan(RelativeSizeSpan(0.9f), start, info.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
        }
        row.addView(text(info, 14f), LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        return row
    }

    private fun explain(box: LinearLayout, btn: TextView) {
        val settings = AppSettings(this)
        val key = settings.apiKey
        if (key.isNullOrBlank()) {
            Toast.makeText(this, R.string.err_no_key, Toast.LENGTH_LONG).show()
            return
        }
        btn.isEnabled = false
        btn.text = "Đang hỏi AI…"
        val model = settings.model
        worker.execute {
            val outcome = runCatching { Usage.explain(OpenRouterClient(key, model), word, sentence) }
            runOnUiThread {
                if (isDestroyed) return@runOnUiThread
                outcome.fold({ box.removeAllViews(); box.addView(text(usageText(it), 15f)) }, {
                    btn.isEnabled = true
                    btn.text = "Thử lại — ${it.message}"
                })
            }
        }
    }

    private fun usageText(n: UsageNote): CharSequence {
        val sb = SpannableStringBuilder()
        fun head(t: String) {
            if (sb.isNotEmpty()) sb.append("\n\n")
            sb.append(t, StyleSpan(Typeface.BOLD), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
            sb.append("\n")
        }
        if (n.meaningHere.isNotEmpty()) { head("Nghĩa ở đây"); sb.append(n.meaningHere) }
        if (n.explanation.isNotEmpty()) { head("Giải thích"); sb.append(n.explanation) }
        if (n.grammar.isNotEmpty()) { head("Cấu trúc"); sb.append(n.grammar.joinToString("\n") { "• $it" }) }
        if (n.examples.isNotEmpty()) {
            head("Ví dụ")
            n.examples.forEachIndexed { i, (zh, py, vi) ->
                if (i > 0) sb.append("\n")
                sb.append("${i + 1}. $zh\n")
                val s = sb.length
                sb.append("   $py\n   $vi")
                sb.setSpan(ForegroundColorSpan(Color.GRAY), s, sb.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
            }
        }
        if (n.collocations.isNotEmpty()) { head("Hay đi với"); sb.append(n.collocations.joinToString(" · ")) }
        if (n.confusables.isNotEmpty()) {
            head("Dễ nhầm với")
            sb.append(n.confusables.joinToString("\n") { (w, diff) -> "• $w — $diff" })
        }
        return sb
    }

    private fun speak() {
        if (ttsReady) tts?.speak(word, TextToSpeech.QUEUE_FLUSH, null, "word")
        else Toast.makeText(this, "Máy chưa có giọng đọc tiếng Trung (Cài đặt → Chuyển văn bản thành giọng nói)",
            Toast.LENGTH_LONG).show()
    }

    // ── small view helpers ────────────────────────────────────────────────

    private fun section(title: String) {
        body.addView(text(title.uppercase(Locale("vi")), 12f).apply {
            alpha = 0.55f
            setTypeface(typeface, Typeface.BOLD)
            letterSpacing = 0.08f
            setPadding(0, dp(18), 0, dp(4))
        })
    }

    private fun text(s: CharSequence, sp: Float) = TextView(this).apply {
        text = s
        setTextSize(TypedValue.COMPLEX_UNIT_SP, sp)
        setTextIsSelectable(true)
    }

    private fun label(label: String, value: String): CharSequence = SpannableStringBuilder().apply {
        append(label, ForegroundColorSpan(Color.GRAY), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
        append(value, StyleSpan(Typeface.BOLD), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
    }

    private fun toned(text: String, t: Token, spaced: Boolean): CharSequence {
        val s = SpannableString(text)
        var idx = 0
        for (syl in t.syllables.filter { it.tone != 0 || !spaced }) {
            val len = if (spaced) syl.marked.length else 1
            Pinyin.TONE_COLORS[syl.tone]?.let {
                if (idx + len <= text.length) s.setSpan(ForegroundColorSpan(it), idx, idx + len,
                    Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
            }
            idx += len + if (spaced) 1 else 0
        }
        return s
    }

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    companion object {
        const val EXTRA_WORD = "word"
        const val EXTRA_SENTENCE = "sentence"
        const val EXTRA_TRANSLATION = "translation"
        private const val ACCENT = 0xFF4F59E6.toInt()
        private val ETYM = mapOf("pictographic" to "Tượng hình", "ideographic" to "Hội ý",
            "pictophonetic" to "Hình thanh")
    }
}
