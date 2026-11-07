package io.github.orms147.transsnip.screen

import android.content.Context
import android.graphics.Color
import android.graphics.Paint
import android.graphics.PixelFormat
import android.graphics.Rect
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.text.TextUtils
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.view.WindowManager
import android.widget.FrameLayout
import android.widget.TextView
import kotlin.math.ceil

/**
 * Full-screen transparent layer drawn by the accessibility service: one box
 * per piece of text, at the text's own position, painted in the colour that
 * was behind it and filled with the translation as it streams in.
 * Tap a box → details popup; tap anywhere else → close.
 */
class ScreenOverlay(
    private val context: Context,
    private val wm: WindowManager,
    private val screen: Rect,
    private val onBoxTap: (Int) -> Unit,
    private val onDismiss: () -> Unit,
) {
    private class Box(val view: TextView, val bounds: Rect, val estPx: Float)

    private val dp = context.resources.displayMetrics.density
    private val root = FrameLayout(context)
    private val boxes = HashMap<Int, Box>()
    private val status = TextView(context)
    private val offset = IntArray(2)
    private var attached = false

    init {
        root.setOnClickListener { onDismiss() }
        status.apply {
            setTextColor(Color.WHITE)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 13f)
            setPadding((14 * dp).toInt(), (7 * dp).toInt(), (14 * dp).toInt(), (7 * dp).toInt())
            background = GradientDrawable().apply {
                cornerRadius = 18 * dp
                setColor(0xE0202124.toInt())
            }
            setOnClickListener { onDismiss() }
            elevation = 8 * dp
        }
        root.addView(status, FrameLayout.LayoutParams(
            FrameLayout.LayoutParams.WRAP_CONTENT, FrameLayout.LayoutParams.WRAP_CONTENT,
            Gravity.BOTTOM or Gravity.CENTER_HORIZONTAL,
        ).apply { bottomMargin = (72 * dp).toInt() })
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
        if (autoHideMs > 0) status.animate().alpha(0f).setStartDelay(autoHideMs).setDuration(300)
            .withEndAction { status.visibility = View.GONE }.start()
        status.text = text.orEmpty()
        status.visibility = if (text.isNullOrEmpty()) View.GONE else View.VISIBLE
    }

    /**
     * Registers where box [i] goes. Nothing is drawn until its translation
     * arrives ([setText]) — the original stays readable meanwhile instead of
     * hiding under an empty card.
     * [source]: the original text — its length vs. the box size gives the original font size.
     */
    fun addBox(i: Int, bounds: Rect, background: Int, source: String) {
        pending[i] = Triple(Rect(bounds), background, source)
    }

    private val pending = HashMap<Int, Triple<Rect, Int, String>>()

    private fun createBox(i: Int): Box? {
        val (bounds, background, source) = pending.remove(i) ?: return null
        val pad = (2 * dp).toInt()
        val est = estimateFontPx(source, bounds).coerceIn(10 * dp, 20 * dp)
        val fg = if (luminance(background) > 0.55) 0xFF111111.toInt() else Color.WHITE
        val view = TextView(context).apply {
            setPadding(pad * 2, pad, pad * 2, pad)
            setTextColor(fg)
            setTextSize(TypedValue.COMPLEX_UNIT_PX, est)
            gravity = Gravity.CENTER_VERTICAL or Gravity.START
            ellipsize = TextUtils.TruncateAt.END
            text = "…"
            this.background = GradientDrawable().apply {
                cornerRadius = 4 * dp
                setColor(background)
            }
            elevation = 1 * dp
            setOnClickListener { onBoxTap(i) }
        }
        val box = Box(view, Rect(bounds), est)
        boxes[i] = box
        root.addView(view, 0, FrameLayout.LayoutParams(bounds.width(), bounds.height()))
        return box
    }

    fun setText(i: Int, text: String) {
        val box = boxes[i] ?: createBox(i) ?: return
        box.view.text = text
        place(i)
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
        val padH = v.paddingLeft + v.paddingRight
        val padV = v.paddingTop + v.paddingBottom
        val paint = Paint().apply { textSize = box.estPx }
        val textLines = v.text.toString().split('\n')
        val desired = (textLines.maxOf { paint.measureText(it) } + padH + 2).toInt()
        // Grow only into free space: up to the next text to the right on the
        // same band, and down to the next text below — never over other text.
        val others = allBounds().filter { it !== b }
        val gap = (2 * dp).toInt()
        val rightLimit = others
            .filter { it.left >= b.right && it.top < b.bottom && it.bottom > b.top }
            .minOfOrNull { it.left - gap } ?: (screen.right - (4 * dp).toInt())
        val maxW = rightLimit.coerceAtLeast(b.left + b.width()) - b.left
        val w = desired.coerceIn(b.width(), maxW)
        val rows = textLines.sumOf { ceil((paint.measureText(it) + 1) / (w - padH).coerceAtLeast(1)).toInt().coerceAtLeast(1) }
        val wantH = (rows * box.estPx * 1.25f + padV).toInt()
        val bottomLimit = others
            .filter { it.top >= b.bottom - gap && it.left < b.left + w && it.right > b.left }
            .minOfOrNull { it.top - gap } ?: screen.bottom
        val maxH = (bottomLimit - b.top).coerceIn(b.height(), b.height() * 3)
        val h = wantH.coerceIn(b.height(), maxH)

        val minPx = 8 * dp
        if (box.estPx > minPx + 1) {
            v.setAutoSizeTextTypeUniformWithConfiguration(minPx.toInt(), box.estPx.toInt(), 1, TypedValue.COMPLEX_UNIT_PX)
        }
        val lp = (v.layoutParams as FrameLayout.LayoutParams)
        lp.width = w
        lp.height = h
        lp.leftMargin = b.left - offset[0]
        lp.topMargin = b.top - offset[1]
        v.layoutParams = lp
    }

    private fun allBounds(): List<Rect> = boxes.values.map { it.bounds } + pending.values.map { it.first }

    /**
     * n glyphs of size f wrapped in a w×h box: rows ≈ h / 1.3f, glyphs per row
     * ≈ w / (f·width) → f ≈ √(w·h / 1.3·Σwidth). Han glyphs are square, Latin
     * ones about half as wide. Never taller than one line of the box.
     */
    private fun estimateFontPx(text: String, b: Rect): Float {
        var units = 0.0
        for (c in text) units += if (c.code >= 0x2E80) 1.0 else if (c.isWhitespace()) 0.3 else 0.55
        if (units <= 0) return b.height() * 0.7f
        val f = Math.sqrt(b.width().toDouble() * b.height() / (1.3 * units)).toFloat()
        // A box is often wider than its text (block elements): the height of
        // one line caps it.
        return minOf(f, b.height() * 0.62f)
    }

    private fun luminance(c: Int): Double =
        (0.299 * Color.red(c) + 0.587 * Color.green(c) + 0.114 * Color.blue(c)) / 255.0
}
