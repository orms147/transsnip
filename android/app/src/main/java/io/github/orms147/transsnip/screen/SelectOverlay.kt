package io.github.orms147.transsnip.screen

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.PixelFormat
import android.graphics.Rect
import android.graphics.RectF
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.util.TypedValue
import android.view.Gravity
import android.view.HapticFeedbackConstants
import android.view.KeyEvent
import android.view.MotionEvent
import android.view.View
import android.view.ViewConfiguration
import android.view.WindowManager
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import io.github.orms147.transsnip.R
import kotlin.math.abs

/**
 * "Select text" mode: the screen frozen as a screenshot, dimmed except where
 * there is text, and that text selectable like in a text field — tap a line,
 * drag across characters, adjust with the two handles — then copy it or
 * translate it. Nothing is sent anywhere until "Translate".
 *
 * Exits on ✕, Back, or after an action. A tap on empty space only clears the
 * selection, so a stray touch never throws the mode away.
 */
@SuppressLint("ViewConstructor")
class SelectOverlay(
    private val context: Context,
    private val wm: WindowManager,
    private val screen: Rect,
    private val shot: Bitmap?,
    private val topInset: Int,
    private val bottomInset: Int,
    private val onCopy: (String) -> Unit,
    private val onTranslate: (String) -> Unit,
    private val onClose: () -> Unit,
) {
    private val dp = context.resources.displayMetrics.density
    private val accent = context.getColor(R.color.accent)
    private val root = Root(context)
    private val board = Board(context)
    private val hint = TextView(context)
    private val actions = LinearLayout(context)
    private var attached = false

    private var model = SelectModel(emptyList())
    private var selA = -1   // glyph indices, selA ≤ selB; −1 = nothing selected
    private var selB = -1

    init {
        root.addView(board, FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT))
        root.addView(topBar(), FrameLayout.LayoutParams(
            FrameLayout.LayoutParams.WRAP_CONTENT, FrameLayout.LayoutParams.WRAP_CONTENT,
            Gravity.BOTTOM or Gravity.CENTER_HORIZONTAL,
        ).apply { bottomMargin = bottomInset + (16 * dp).toInt() })
        actions.apply {
            orientation = LinearLayout.HORIZONTAL
            background = pill(0xF2202124.toInt())
            elevation = 10 * dp
            visibility = View.GONE
            addView(button(context.getString(R.string.select_copy)) { act(onCopy) })
            addView(divider())
            addView(button(context.getString(R.string.select_translate)) { act(onTranslate) })
        }
        root.addView(actions, FrameLayout.LayoutParams(FrameLayout.LayoutParams.WRAP_CONTENT, FrameLayout.LayoutParams.WRAP_CONTENT))
    }

    fun attach() {
        val lp = WindowManager.LayoutParams(
            screen.width(), screen.height(),
            WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
            // Focusable: Back comes here (and closes the mode), not to the frozen app.
            WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN or WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
            PixelFormat.TRANSLUCENT,
        ).apply {
            gravity = Gravity.TOP or Gravity.START
            if (Build.VERSION.SDK_INT >= 30) {
                fitInsetsTypes = 0
                layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_ALWAYS
            } else if (Build.VERSION.SDK_INT >= 28) {
                layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES
            }
        }
        root.alpha = 0f
        runCatching { wm.addView(root, lp) }.onSuccess {
            attached = true
            root.animate().alpha(1f).setDuration(150).start()
            root.isFocusableInTouchMode = true
            root.requestFocus()
        }
    }

    fun detach() {
        if (!attached) return
        attached = false
        runCatching { wm.removeView(root) }
    }

    fun setHint(text: String) {
        hint.text = text
    }

    /** New set of text (OCR arrived): keeps the selection if its ends are still there. */
    fun setLines(lines: List<TextLine>) {
        val a = model.glyphs.getOrNull(selA)
        val b = model.glyphs.getOrNull(selB)
        model = SelectModel(lines)
        selA = a?.let { model.glyphs.indexOf(it) } ?: -1
        selB = b?.let { model.glyphs.indexOf(it) } ?: -1
        if (selA < 0 || selB < 0) clear() else placeActions()
        board.invalidate()
    }

    fun allText() = model.text(model.all)
    val hasText get() = !model.isEmpty

    private fun act(action: (String) -> Unit) {
        val text = if (selA >= 0) model.text(selA..selB) else ""
        if (text.isNotEmpty()) action(text)
    }

    private fun select(a: Int, b: Int) {
        val (x, y) = if (a <= b) a to b else b to a
        if (x != selA || y != selB) {
            if (Build.VERSION.SDK_INT >= 27 && selA >= 0) board.performHapticFeedback(HapticFeedbackConstants.TEXT_HANDLE_MOVE)
            selA = x; selB = y
            board.invalidate()
        }
    }

    private fun clear() {
        selA = -1; selB = -1
        actions.visibility = View.GONE
        board.invalidate()
    }

    /** The action bar sits above the selection, or below it when there's no room. */
    private fun placeActions() {
        if (selA < 0) return actions.run { visibility = View.GONE }
        val ga = model.glyphs[selA]
        val top = (selA..selB).minOf { model.glyphs[it].t }
        val bottom = (selA..selB).maxOf { model.glyphs[it].b }
        actions.measure(0, 0)
        val w = actions.measuredWidth
        val h = actions.measuredHeight
        val gap = (14 * dp).toInt()
        // Clear of the status bar above and of the bar with "Copy all" / ✕ below.
        val minTop = topInset + gap
        val maxTop = screen.height() - bottomInset - (76 * dp).toInt() - h
        val y = if (top - gap - h >= minTop) top - gap - h
        else (bottom + gap + HANDLE_R * 2 * dp).toInt().coerceAtMost(maxTop)
        val lp = actions.layoutParams as FrameLayout.LayoutParams
        lp.leftMargin = (ga.l - w / 4).coerceIn(gap, (screen.width() - w - gap).coerceAtLeast(gap))
        lp.topMargin = y
        actions.layoutParams = lp
        actions.visibility = View.VISIBLE
    }

    private fun topBar() = LinearLayout(context).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.CENTER_VERTICAL
        background = pill(0xF2202124.toInt())
        elevation = 10 * dp
        hint.apply {
            setTextColor(0xCCFFFFFF.toInt())
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 14f)
            setPadding((16 * dp).toInt(), 0, (8 * dp).toInt(), 0)
            text = context.getString(R.string.select_hint)
        }
        addView(hint)
        addView(button(context.getString(R.string.select_copy_all)) { if (hasText) onCopy(allText()) })
        addView(button("✕") { onClose() }.apply { contentDescription = context.getString(R.string.close) })
    }

    private fun button(label: String, onClick: () -> Unit) = TextView(context).apply {
        text = label
        setTextColor(Color.WHITE)
        setTextSize(TypedValue.COMPLEX_UNIT_SP, 15f)
        gravity = Gravity.CENTER
        minHeight = (44 * dp).toInt()
        setPadding((14 * dp).toInt(), 0, (14 * dp).toInt(), 0)
        background = context.getDrawable(android.R.drawable.list_selector_background)
        setOnClickListener { onClick() }
    }

    private fun divider() = View(context).apply {
        setBackgroundColor(0x33FFFFFF)
        layoutParams = LinearLayout.LayoutParams((1 * dp).toInt().coerceAtLeast(1), (24 * dp).toInt()).apply {
            gravity = Gravity.CENTER_VERTICAL
        }
    }

    private fun pill(color: Int) = GradientDrawable().apply {
        cornerRadius = 22 * dp
        setColor(color)
    }

    /** Takes Back. */
    private inner class Root(context: Context) : FrameLayout(context) {
        override fun dispatchKeyEvent(event: KeyEvent): Boolean {
            if (event.keyCode == KeyEvent.KEYCODE_BACK) {
                if (event.action == KeyEvent.ACTION_UP) onClose()
                return true
            }
            return super.dispatchKeyEvent(event)
        }
    }

    /** The frozen screen, the text highlights, the selection and its handles; and the touch logic. */
    private inner class Board(context: Context) : View(context) {
        private val dim = Paint().apply { color = 0x8C000000.toInt() }
        private val selPaint = Paint().apply { color = 0x66000000 or (accent and 0xFFFFFF) }
        private val handlePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = accent }
        private val noShot = Paint().apply { color = 0x33FFFFFF }
        private val src = Rect()
        private val dst = RectF()
        private val slop = ViewConfiguration.get(context).scaledTouchSlop
        private val handleR = HANDLE_R * dp

        override fun onDraw(canvas: Canvas) {
            val s = shot?.takeIf { !it.isRecycled }
            if (s != null) canvas.drawBitmap(s, 0f, 0f, null)
            canvas.drawRect(0f, 0f, width.toFloat(), height.toFloat(), dim)
            // Text stays bright: that's what can be selected.
            val pad = (3 * dp).toInt()
            for (line in model.lines) {
                src.set(line.l - pad, line.t - pad, line.r + pad, line.b + pad)
                if (s != null) {
                    src.intersect(0, 0, s.width, s.height)
                    dst.set(src)
                    canvas.drawBitmap(s, src, dst, null)
                } else {
                    canvas.drawRect(src, noShot)
                }
            }
            if (selA < 0) return
            // The selection, merged per line.
            var i = selA
            while (i <= selB) {
                val li = model.lineIndex(i)
                val end = minOf(selB, model.lineRange(li).last)
                val a = model.glyphs[i]
                val b = model.glyphs[end]
                val line = model.lines[li]
                canvas.drawRect(a.l.toFloat(), line.t.toFloat(), b.r.toFloat(), line.b.toFloat(), selPaint)
                i = end + 1
            }
            drawHandle(canvas, startHandle(), left = true)
            drawHandle(canvas, endHandle(), left = false)
        }

        /** Where each handle's knob is: hanging below the first / last selected glyph. */
        private fun startHandle(): Pair<Float, Float> {
            val g = model.glyphs[selA]
            return g.l.toFloat() to model.lines[model.lineIndex(selA)].b + handleR
        }

        private fun endHandle(): Pair<Float, Float> {
            val g = model.glyphs[selB]
            return g.r.toFloat() to model.lines[model.lineIndex(selB)].b + handleR
        }

        private fun drawHandle(canvas: Canvas, at: Pair<Float, Float>, left: Boolean) {
            val (x, y) = at
            canvas.drawCircle(x, y, handleR, handlePaint)
            // The square corner points at the edge of the text, like Android's own handles.
            if (left) canvas.drawRect(x, y - handleR, x + handleR, y, handlePaint)
            else canvas.drawRect(x - handleR, y - handleR, x, y, handlePaint)
        }

        private var mode = 0          // 0 none, 1 maybe tap, 2 drag-select, 3 start handle, 4 end handle
        private var downX = 0f
        private var downY = 0f
        private var anchor = -1
        private var grabDy = 0f       // finger offset from the handle's line, kept while dragging it

        @SuppressLint("ClickableViewAccessibility")
        override fun onTouchEvent(e: MotionEvent): Boolean {
            val x = e.x
            val y = e.y
            when (e.actionMasked) {
                MotionEvent.ACTION_DOWN -> {
                    downX = x; downY = y
                    actions.visibility = View.GONE
                    mode = 1
                    if (selA >= 0) {
                        val reach = handleR * 2.4f
                        val (sx, sy) = startHandle()
                        val (ex, ey) = endHandle()
                        val ds = abs(x - sx) + abs(y - sy)
                        val de = abs(x - ex) + abs(y - ey)
                        if (de < reach * 1.4f && de <= ds) { mode = 4; grabDy = y - model.glyphs[selB].cy }
                        else if (ds < reach * 1.4f) { mode = 3; grabDy = y - model.glyphs[selA].cy }
                    }
                }
                MotionEvent.ACTION_MOVE -> when (mode) {
                    1 -> if (abs(x - downX) > slop || abs(y - downY) > slop) {
                        anchor = model.nearest(downX.toInt(), downY.toInt())
                        if (anchor >= 0) {
                            mode = 2
                            performHapticFeedback(HapticFeedbackConstants.KEYBOARD_TAP)
                            select(anchor, model.nearest(x.toInt(), y.toInt()))
                        }
                    }
                    2 -> select(anchor, model.nearest(x.toInt(), y.toInt()))
                    3, 4 -> {
                        val g = model.nearest(x.toInt(), (y - grabDy).toInt())
                        if (g >= 0) {
                            // Dragged past the other handle: they swap roles.
                            if (mode == 3) { if (g > selB) { select(selB, g); mode = 4 } else select(g, selB) }
                            else { if (g < selA) { select(g, selA); mode = 3 } else select(selA, g) }
                        }
                    }
                }
                MotionEvent.ACTION_UP -> {
                    if (mode == 1) tap(x.toInt(), y.toInt())
                    mode = 0
                    placeActions()
                }
                MotionEvent.ACTION_CANCEL -> { mode = 0; placeActions() }
            }
            return true
        }

        /** Tap a line → that line; tap it again → its whole paragraph; tap empty → clear. */
        private fun tap(x: Int, y: Int) {
            val g = model.hit(x, y, (10 * dp).toInt())
            if (g < 0) return clear()
            val line = model.lineRange(model.lineIndex(g))
            if (selA == line.first && selB == line.last) {
                val para = model.paragraphRange(model.lineIndex(g))
                select(para.first, para.last)
            } else {
                selA = -1
                select(line.first, line.last)
            }
        }
    }

    companion object {
        private const val HANDLE_R = 11f

        /**
         * Lines of one accessibility item, split where its characters move
         * down a row. Items without per-character boxes are one block (still
         * copyable whole).
         */
        fun linesOf(item: ScreenItem, source: Int): List<TextLine> {
            val chars = item.chars
            val b = item.bounds
            if (chars == null || chars.all { it.isEmpty }) {
                return listOf(TextLine(listOf(Glyph(item.text, b.left, b.top, b.right, b.bottom)), source))
            }
            val out = ArrayList<TextLine>()
            var cur = ArrayList<Glyph>()
            var hard = false
            fun flush() {
                if (cur.isNotEmpty()) { out += TextLine(cur, source, hard); hard = false }
                cur = ArrayList()
            }
            val text = item.text
            var i = 0
            while (i < text.length) {
                val n = Character.charCount(text.codePointAt(i))
                val s = text.substring(i, i + n)
                val box = chars.getOrNull(i)
                i += n
                if (s == "\n") { flush(); hard = true; continue }
                if (box == null || box.isEmpty) {
                    // An invisible space still separates words.
                    if (s.isBlank() && cur.isNotEmpty()) cur[cur.size - 1] = cur.last().let { Glyph(it.text + " ", it.l, it.t, it.r, it.b) }
                    continue
                }
                val prev = cur.lastOrNull()
                if (prev != null && box.centerY() > prev.b) flush()
                cur += Glyph(s, box.left, box.top, box.right, box.bottom)
            }
            flush()
            return out
        }

        /** OCR'd lines of one block: word boxes split into characters, spaces kept between Latin words. */
        fun linesOf(block: Ocr.Block, source: Int): List<TextLine> = block.lines.mapNotNull { line ->
            val glyphs = ArrayList<Glyph>()
            for ((k, w) in line.words.withIndex()) {
                val parts = SelectModel.splitEvenly(w.text, w.box.left, w.box.top, w.box.right, w.box.bottom)
                if (parts.isEmpty()) continue
                val next = line.words.getOrNull(k + 1)?.text?.firstOrNull()
                if (next != null && !SelectModel.isCjk(w.text.last()) && !SelectModel.isCjk(next)) {
                    val last = parts.last()
                    glyphs += parts.dropLast(1)
                    glyphs += Glyph(last.text + " ", last.l, last.t, last.r, last.b)
                } else {
                    glyphs += parts
                }
            }
            if (glyphs.isEmpty()) null else TextLine(glyphs, source)
        }
    }
}
