package io.github.orms147.transsnip.screen

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.Color
import android.graphics.Paint
import android.graphics.PixelFormat
import android.graphics.PointF
import android.graphics.Rect
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.SystemClock
import android.text.TextUtils
import android.util.TypedValue
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.ViewConfiguration
import android.view.WindowManager
import android.widget.FrameLayout
import android.widget.TextView
import io.github.orms147.transsnip.R
import kotlin.math.abs
import kotlin.math.ceil
import kotlin.math.hypot

/**
 * Full-screen transparent layer drawn by the accessibility service: one box
 * per piece of text, at the text's own position, painted in the colour that
 * was behind it and filled with the translation as it streams in.
 *
 * Touch:
 *  - tap a box → details popup;   hold a box → peek at the original;
 *  - swipe anywhere → [onSwipe] (the service replays it on the app below,
 *    so the page scrolls, then translates the new screen);
 *  - tap empty space → close.
 */
class ScreenOverlay(
    private val context: Context,
    private val wm: WindowManager,
    private val screen: Rect,
    private val onBoxTap: (Int) -> Unit,
    private val onDismiss: () -> Unit,
    private val onSwipe: (List<PointF>, Long) -> Unit,
) {
    private class Box(val view: TextView, var bounds: Rect, var estPx: Float, val source: String,
                      val fill: Int, val fg: Int) {
        var translation: String? = null
        var peeking = false
    }

    private val dp = context.resources.displayMetrics.density
    private val root = TouchLayer(context)
    private val boxes = HashMap<Int, Box>()
    private val status = TextView(context)
    private val offset = IntArray(2)
    private var attached = false
    private val accent = context.getColor(R.color.accent)

    init {
        status.apply {
            setTextColor(Color.WHITE)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 13f)
            setPadding((14 * dp).toInt(), (7 * dp).toInt(), (14 * dp).toInt(), (7 * dp).toInt())
            background = GradientDrawable().apply {
                cornerRadius = 18 * dp
                setColor(0xE6202124.toInt())
            }
            elevation = 8 * dp
            visibility = View.GONE
        }
        root.addView(status, FrameLayout.LayoutParams(
            FrameLayout.LayoutParams.WRAP_CONTENT, FrameLayout.LayoutParams.WRAP_CONTENT,
            Gravity.BOTTOM or Gravity.CENTER_HORIZONTAL,
        ).apply { bottomMargin = (64 * dp).toInt() })
    }

    fun attach() {
        val lp = WindowManager.LayoutParams(
            screen.width(), screen.height(),
            WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN or
                WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
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
        wm.addView(root, lp)
        attached = true
        root.animate().alpha(1f).setDuration(120).start()
        // Boxes are placed in screen coordinates; correct for wherever the
        // window actually landed (status bar / cutout on some ROMs).
        root.post {
            if (!attached) return@post
            root.getLocationOnScreen(offset)
            boxes.keys.forEach(::place)
        }
    }

    fun detach() {
        if (!attached) return
        attached = false
        runCatching { wm.removeView(root) }
    }

    /** [autoHideMs] > 0: fade the chip out after that long (it covers content). */
    fun setStatus(text: String?, autoHideMs: Long = 0) {
        status.animate().cancel()
        status.alpha = 1f
        status.text = text.orEmpty()
        status.visibility = if (text.isNullOrEmpty()) View.GONE else View.VISIBLE
        if (autoHideMs > 0 && !text.isNullOrEmpty()) {
            status.animate().alpha(0f).setStartDelay(autoHideMs).setDuration(300)
                .withEndAction { status.visibility = View.GONE }.start()
        }
    }

    /**
     * Box [i] appears at once as a faint outline — "found this, translating" —
     * leaving the original readable, and fills in when [setText] delivers.
     * [fontPx]: the original text size if the app reported it; otherwise it
     * is guessed from [source]'s length vs. the box size.
     */
    @SuppressLint("ClickableViewAccessibility")
    fun addBox(i: Int, bounds: Rect, background: Int, source: String, fontPx: Float? = null) {
        val pad = (2 * dp).toInt()
        val est = fontPx?.coerceIn(9 * dp, 28 * dp) ?: estimateFontPx(source, bounds).coerceIn(10 * dp, 17 * dp)
        val fg = if (luminance(background) > 0.55) 0xFF111111.toInt() else Color.WHITE
        val view = TextView(context).apply {
            setPadding(pad * 2, pad, pad * 2, pad)
            setTextColor(fg)
            setTextSize(TypedValue.COMPLEX_UNIT_PX, est)
            gravity = Gravity.CENTER_VERTICAL or Gravity.START
            ellipsize = TextUtils.TruncateAt.END
        }
        val box = Box(view, Rect(bounds), est, source, background, fg)
        boxes[i] = box
        paintPending(box)
        view.setOnClickListener { if (box.translation != null) onBoxTap(i) }
        view.setOnLongClickListener {
            if (box.translation == null) return@setOnLongClickListener false
            box.peeking = true
            showText(box, box.source)
            true
        }
        view.setOnTouchListener { _, e ->
            if (box.peeking && (e.actionMasked == MotionEvent.ACTION_UP || e.actionMasked == MotionEvent.ACTION_CANCEL)) {
                box.peeking = false
                showText(box, box.translation.orEmpty())
            }
            false
        }
        root.addView(view, 0, FrameLayout.LayoutParams(bounds.width(), bounds.height()))
        place(i)
    }

    /** Better geometry learned later (OCR): where the glyphs really are, and their size. */
    fun refine(i: Int, glyphs: Rect, fontPx: Float) {
        val box = boxes[i] ?: return
        if (glyphs.width() < 4 || glyphs.height() < 4) return
        box.bounds = Rect(glyphs)
        box.estPx = fontPx.coerceIn(9 * dp, 28 * dp)
        box.view.setAutoSizeTextTypeWithDefaults(TextView.AUTO_SIZE_TEXT_TYPE_NONE)
        box.view.setTextSize(TypedValue.COMPLEX_UNIT_PX, box.estPx)
        place(i)
        // Neighbours may now have room to grow.
        boxes.keys.filter { it != i }.forEach(::place)
    }

    fun setText(i: Int, text: String) {
        val box = boxes[i] ?: return
        val first = box.translation == null
        box.translation = text
        if (first) paintFilled(box)
        if (!box.peeking) showText(box, text)
        if (first) {
            box.view.alpha = 0f
            box.view.animate().alpha(1f).setDuration(140).start()
        }
    }

    private fun showText(box: Box, text: String) {
        box.view.text = text
        place(boxes.entries.first { it.value === box }.key)
    }

    private fun paintPending(box: Box) {
        box.view.background = GradientDrawable().apply {
            cornerRadius = 4 * dp
            setColor(0x14000000 or (accent and 0xFFFFFF))
            setStroke((1.5f * dp).toInt(), 0x99000000.toInt() or (accent and 0xFFFFFF))
        }
        box.view.elevation = 0f
    }

    private fun paintFilled(box: Box) {
        box.view.background = GradientDrawable().apply {
            cornerRadius = 4 * dp
            setColor(box.fill)
        }
        box.view.elevation = 1 * dp
    }

    /**
     * Size the box for its text: keep the original font size when possible,
     * widening to the right (Vietnamese runs 2–3× wider than the Chinese it
     * replaces) and then growing down; shrink the font only for what's left.
     */
    private fun place(i: Int) {
        val box = boxes[i] ?: return
        val b = box.bounds
        val v = box.view
        val lp = (v.layoutParams as? FrameLayout.LayoutParams) ?: return
        lp.leftMargin = b.left - offset[0]
        lp.topMargin = b.top - offset[1]
        if (v.text.isNullOrEmpty()) {
            lp.width = b.width()
            lp.height = b.height()
            v.layoutParams = lp
            return
        }
        val padH = v.paddingLeft + v.paddingRight
        val padV = v.paddingTop + v.paddingBottom
        val paint = Paint().apply { textSize = box.estPx }
        val textLines = v.text.toString().split('\n')
        val desired = (textLines.maxOf { paint.measureText(it) } + padH + 2).toInt()
        // Grow only into free space: up to the next text to the right on the
        // same band, and down to the next text below — never over other text.
        val others = boxes.values.filter { it !== box }.map { it.bounds }
        val gap = (2 * dp).toInt()
        // Neighbouring views often touch or overlap by a few px: anything that
        // starts near or past this box's right edge counts as a neighbour.
        val slack = (8 * dp).toInt()
        val rightLimit = others
            .filter { it.left >= b.right - slack && it.left > b.left && it.top < b.bottom && it.bottom > b.top }
            .minOfOrNull { maxOf(it.left - gap, b.right) } ?: (screen.right - (4 * dp).toInt())
        val maxW = rightLimit.coerceAtLeast(b.left + b.width()) - b.left
        val w = desired.coerceIn(b.width(), maxW)
        val rows = textLines.sumOf { ceil((paint.measureText(it) + 1) / (w - padH).coerceAtLeast(1)).toInt().coerceAtLeast(1) }
        val wantH = (rows * box.estPx * 1.25f + padV).toInt()
        val bottomLimit = others
            .filter { it.top >= b.bottom - gap && it.left < b.left + w && it.right > b.left }
            .minOfOrNull { it.top - gap } ?: screen.bottom
        // A one-line original (name, date, button) stays one line: wrapping
        // would spill onto its neighbours, so the font shrinks a little instead.
        // Longer text may take about one extra line before shrinking.
        val singleLine = textLines.size == 1 && b.height() < box.estPx * 1.3f * 1.6f
        val oneMore = b.height() + (box.estPx * 1.3f).toInt()
        // Vietnamese diacritics stack above and below: a line of it needs a
        // bit more height than the Han characters it replaces.
        val maxH = if (singleLine) maxOf(b.height(), (box.estPx * 1.35f).toInt() + padV)
        else (bottomLimit - b.top).coerceIn(b.height(), maxOf(oneMore, (b.height() * 1.5f).toInt()))
        val h = wantH.coerceIn(b.height(), maxH)

        // Never below a readable size: what doesn't fit ends in "…" (tap → full text).
        val minPx = if (singleLine) maxOf(box.estPx * 0.6f, minOf(9 * dp, box.estPx)) else minOf(10 * dp, box.estPx)
        if (box.estPx > minPx + 1) {
            v.setAutoSizeTextTypeUniformWithConfiguration(minPx.toInt(), box.estPx.toInt(), 1, TypedValue.COMPLEX_UNIT_PX)
        }
        v.maxLines = if (singleLine) 1 else ((h - padV) / (minPx * 1.2f)).toInt().coerceAtLeast(1)
        lp.width = w
        lp.height = h
        v.layoutParams = lp
    }

    /**
     * n glyphs of size f wrapped in a w×h box: rows ≈ h / 1.3f, glyphs per row
     * ≈ w / (f·width) → f ≈ √(w·h / 1.3·Σwidth). Han glyphs are square, Latin
     * ones about half as wide.
     */
    private fun estimateFontPx(text: String, b: Rect): Float {
        var units = 0.0
        for (c in text) units += if (c.code >= 0x2E80) 1.0 else if (c.isWhitespace()) 0.3 else 0.55
        if (units <= 0) return b.height() * 0.6f
        val f = Math.sqrt(b.width().toDouble() * b.height() / (1.3 * units)).toFloat()
        // A box is often wider than its text (block elements): the height of
        // one line caps it.
        return minOf(f, b.height() * 0.62f)
    }

    private fun luminance(c: Int): Double =
        (0.299 * Color.red(c) + 0.587 * Color.green(c) + 0.114 * Color.blue(c)) / 255.0

    /**
     * Steals the gesture from a box as soon as the finger travels (so a swipe
     * that starts on a box still scrolls), records its path in screen
     * coordinates, and reports swipe / tap-on-empty.
     */
    private inner class TouchLayer(context: Context) : FrameLayout(context) {
        private val slop = ViewConfiguration.get(context).scaledTouchSlop
        private val path = ArrayList<PointF>()
        private var downAt = 0L
        private var swiping = false

        override fun onInterceptTouchEvent(e: MotionEvent): Boolean {
            track(e)
            return swiping
        }

        @SuppressLint("ClickableViewAccessibility")
        override fun onTouchEvent(e: MotionEvent): Boolean {
            track(e)
            if (e.actionMasked == MotionEvent.ACTION_UP) {
                if (swiping) onSwipe(ArrayList(path), (SystemClock.uptimeMillis() - downAt).coerceAtLeast(50))
                else onDismiss()
            }
            return true
        }

        private fun track(e: MotionEvent) {
            when (e.actionMasked) {
                MotionEvent.ACTION_DOWN -> {
                    path.clear()
                    swiping = false
                    downAt = SystemClock.uptimeMillis()
                    path += PointF(e.rawX, e.rawY)
                }
                MotionEvent.ACTION_MOVE -> {
                    val last = path.lastOrNull() ?: return
                    if (hypot(e.rawX - last.x, e.rawY - last.y) > 4) path += PointF(e.rawX, e.rawY)
                    val first = path.first()
                    if (!swiping && (abs(e.rawX - first.x) > slop || abs(e.rawY - first.y) > slop)) swiping = true
                }
            }
        }
    }
}
