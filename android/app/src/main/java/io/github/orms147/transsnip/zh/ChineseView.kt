package io.github.orms147.transsnip.zh

import android.content.Context
import android.graphics.Color
import android.text.SpannableString
import android.text.SpannableStringBuilder
import android.text.Spanned
import android.text.TextPaint
import android.text.method.LinkMovementMethod
import android.text.style.ClickableSpan
import android.text.style.ForegroundColorSpan
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.TextView

/** Precomputed (off the main thread) data for one Chinese source text. */
class ChineseText(
    val text: String,
    val tokens: List<Token>,
    val hanviet: List<String>,     // per token ("" for non-words)
    val sentenceHanviet: String,
)

/**
 * Chinese source block of the popup (desktop: display/popup/chinese.py).
 * Short text: one cell per word — tone-coloured pinyin over the characters,
 * Hán-Việt below — plus the sentence's Hán-Việt. Long text starts compact
 * (plain flowing characters, tap a word) because a paragraph of annotated
 * cells is a wall of colour; a toggle switches views. Tapping a word calls
 * `onWord(word, start, end)` with its position in the text.
 */
class ChineseView(context: Context) : LinearLayout(context) {

    var onWord: ((word: String, start: Int, end: Int) -> Unit)? = null

    private val toggle = TextView(context)
    private val flow = FlowLayout(context)
    private val compact = TextView(context)
    private val hvLine = TextView(context)
    private var data: ChineseText? = null
    private var isCompact = false

    init {
        orientation = VERTICAL
        toggle.apply {
            gravity = Gravity.END
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 12f)
            setTextColor(ACCENT)
            setPadding(0, 0, 0, dp(6))
            setOnClickListener { isCompact = !isCompact; render() }
        }
        compact.apply {
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 19f)
            setLineSpacing(0f, 1.35f)
            movementMethod = LinkMovementMethod.getInstance()
            highlightColor = 0x334F59E6
        }
        hvLine.apply {
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 14f)
            alpha = 0.75f
            setPadding(0, dp(8), 0, 0)
            setTextIsSelectable(true)
        }
        addView(toggle, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT))
        addView(compact, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT))
        addView(flow, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT))
        addView(hvLine, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT))
    }

    fun bind(d: ChineseText) {
        data = d
        val long = d.text.count { Pinyin.isHan(it) } > COMPACT_HAN_CHARS
        isCompact = long
        toggle.visibility = if (long) View.VISIBLE else View.GONE
        render()
    }

    private fun render() {
        val d = data ?: return
        toggle.text = if (isCompact) "Hiện pinyin + Hán-Việt từng từ" else "Thu gọn"
        compact.visibility = if (isCompact) View.VISIBLE else View.GONE
        flow.visibility = if (isCompact) View.GONE else View.VISIBLE
        // The whole paragraph's Hán-Việt is a second wall of text in compact
        // view — there each word's reading is one tap away on its card.
        hvLine.visibility = if (isCompact || d.sentenceHanviet.isBlank()) View.GONE else View.VISIBLE
        if (isCompact) renderCompact(d) else renderCells(d)
        hvLine.text = SpannableString("Hán-Việt: ${d.sentenceHanviet}").apply {
            setSpan(ForegroundColorSpan(Color.GRAY), 0, 9, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
        }
    }

    private fun renderCompact(d: ChineseText) {
        val sb = SpannableStringBuilder()
        var pos = 0
        for (t in d.tokens) {
            val start = sb.length
            sb.append(t.text)
            if (t.isWord) {
                val (a, b) = pos to pos + t.text.length
                sb.setSpan(object : ClickableSpan() {
                    override fun onClick(widget: View) { onWord?.invoke(t.text, a, b) }
                    override fun updateDrawState(ds: TextPaint) { ds.isUnderlineText = false }
                }, start, sb.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
            }
            pos += t.text.length
        }
        compact.text = sb
    }

    private fun renderCells(d: ChineseText) {
        flow.removeAllViews()
        var pos = 0
        d.tokens.forEachIndexed { i, t ->
            val (a, b) = pos to pos + t.text.length
            pos = b
            if (t.text.isBlank()) return@forEachIndexed
            flow.addView(cell(t, d.hanviet[i]).apply {
                if (t.isWord) setOnClickListener { onWord?.invoke(t.text, a, b) }
            })
        }
    }

    private fun cell(t: Token, hv: String): View {
        val col = LinearLayout(context).apply {
            orientation = VERTICAL
            gravity = Gravity.CENTER_HORIZONTAL
            setPadding(dp(3), dp(2), dp(3), dp(2))
            if (t.isWord) {
                val tv = TypedValue()
                context.theme.resolveAttribute(android.R.attr.selectableItemBackground, tv, true)
                setBackgroundResource(tv.resourceId)
            }
        }
        fun line(text: CharSequence, sp: Float, alpha: Float = 1f) = TextView(context).apply {
            this.text = text
            setTextSize(TypedValue.COMPLEX_UNIT_SP, sp)
            this.alpha = alpha
            gravity = Gravity.CENTER_HORIZONTAL
        }
        if (t.isWord) {
            col.addView(line(colored(t.syllables.joinToString(" ") { it.marked }, t, spaced = true), 12f))
            col.addView(line(colored(t.text, t, spaced = false), 22f))
            col.addView(line(hv, 11f, 0.6f))
        } else {
            col.addView(line(" ", 12f))
            col.addView(line(t.text, 22f))
            col.addView(line(" ", 11f))
        }
        return col
    }

    /** Colour each syllable (or character) by its tone. */
    private fun colored(text: String, t: Token, spaced: Boolean): CharSequence {
        val s = SpannableString(text)
        var idx = 0
        for (syl in t.syllables) {
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
        const val COMPACT_HAN_CHARS = 40
        private const val ACCENT = 0xFF4F59E6.toInt()
    }
}

/** Left-to-right layout that wraps children onto new lines. */
class FlowLayout(context: Context) : ViewGroup(context) {
    private val hGap = (2 * resources.displayMetrics.density).toInt()
    private val vGap = (4 * resources.displayMetrics.density).toInt()

    override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) {
        val maxW = MeasureSpec.getSize(widthMeasureSpec) - paddingLeft - paddingRight
        var x = 0
        var y = 0
        var lineH = 0
        for (i in 0 until childCount) {
            val c = getChildAt(i)
            if (c.visibility == GONE) continue
            measureChild(c, MeasureSpec.makeMeasureSpec(maxW, MeasureSpec.AT_MOST), heightMeasureSpec)
            if (x > 0 && x + c.measuredWidth > maxW) {
                x = 0
                y += lineH + vGap
                lineH = 0
            }
            x += c.measuredWidth + hGap
            lineH = maxOf(lineH, c.measuredHeight)
        }
        setMeasuredDimension(MeasureSpec.getSize(widthMeasureSpec), y + lineH + paddingTop + paddingBottom)
    }

    override fun onLayout(changed: Boolean, l: Int, t: Int, r: Int, b: Int) {
        val maxW = r - l - paddingLeft - paddingRight
        var x = 0
        var y = 0
        var lineH = 0
        for (i in 0 until childCount) {
            val c = getChildAt(i)
            if (c.visibility == GONE) continue
            if (x > 0 && x + c.measuredWidth > maxW) {
                x = 0
                y += lineH + vGap
                lineH = 0
            }
            c.layout(paddingLeft + x, paddingTop + y, paddingLeft + x + c.measuredWidth,
                paddingTop + y + c.measuredHeight)
            x += c.measuredWidth + hGap
            lineH = maxOf(lineH, c.measuredHeight)
        }
    }
}
