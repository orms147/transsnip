package io.github.orms147.transsnip.screen

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.DashPathEffect
import android.graphics.Paint
import android.graphics.PixelFormat
import android.graphics.Rect
import android.graphics.RectF
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.text.TextUtils
import android.util.TypedValue
import android.view.Gravity
import android.view.KeyEvent
import android.view.MotionEvent
import android.view.View
import android.view.WindowManager
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import io.github.orms147.transsnip.R
import kotlin.math.max
import kotlin.math.min

private fun overlayParams(screen: Rect, touchable: Boolean, focusable: Boolean) = WindowManager.LayoutParams(
    screen.width(), screen.height(),
    WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
    (if (focusable) 0 else WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE) or
        (if (touchable) 0 else WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE) or
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

/**
 * "Video subtitles", step 1: drag a box around where the subtitles are.
 * The video keeps playing underneath (dimmed outside the box). The last box
 * is drawn already — "Use last box" or just drag a new one. Back / ✕ cancels.
 */
@SuppressLint("ViewConstructor")
class RegionPicker(
    private val context: Context,
    private val wm: WindowManager,
    private val screen: Rect,
    private val topInset: Int,
    private val last: Rect?,
    private val onPicked: (Rect) -> Unit,
    private val onCancel: () -> Unit,
) {
    private val dp = context.resources.displayMetrics.density
    private val accent = context.getColor(R.color.accent)
    private var box: Rect? = last?.let { Rect(it) }
    private var attached = false

    private val root = object : FrameLayout(context) {
        override fun dispatchKeyEvent(event: KeyEvent): Boolean {
            if (event.keyCode == KeyEvent.KEYCODE_BACK) {
                if (event.action == KeyEvent.ACTION_UP) onCancel()
                return true
            }
            return super.dispatchKeyEvent(event)
        }
    }

    private val board = object : View(context) {
        private val dim = Paint().apply { color = 0x99000000.toInt() }
        private val stroke = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            style = Paint.Style.STROKE
            strokeWidth = 2.5f * dp
            color = accent
        }
        private var downX = 0f
        private var downY = 0f

        override fun onDraw(canvas: Canvas) {
            val w = width.toFloat()
            val h = height.toFloat()
            val b = box
            if (b == null) {
                canvas.drawRect(0f, 0f, w, h, dim)
                return
            }
            // Dim everything but the box.
            canvas.drawRect(0f, 0f, w, b.top.toFloat(), dim)
            canvas.drawRect(0f, b.bottom.toFloat(), w, h, dim)
            canvas.drawRect(0f, b.top.toFloat(), b.left.toFloat(), b.bottom.toFloat(), dim)
            canvas.drawRect(b.right.toFloat(), b.top.toFloat(), w, b.bottom.toFloat(), dim)
            canvas.drawRoundRect(RectF(b), 6 * dp, 6 * dp, stroke)
        }

        @SuppressLint("ClickableViewAccessibility")
        override fun onTouchEvent(e: MotionEvent): Boolean {
            when (e.actionMasked) {
                MotionEvent.ACTION_DOWN -> { downX = e.x; downY = e.y }
                MotionEvent.ACTION_MOVE -> {
                    box = Rect(min(downX, e.x).toInt(), min(downY, e.y).toInt(),
                        max(downX, e.x).toInt(), max(downY, e.y).toInt())
                    invalidate()
                }
                MotionEvent.ACTION_UP -> {
                    val b = box
                    // A real box (not a stray tap) starts right away.
                    if (b != null && b.width() >= 60 * dp && b.height() >= 20 * dp &&
                        (b.width() > 0 && (abs(e.x - downX) > 8 * dp || abs(e.y - downY) > 8 * dp))) {
                        onPicked(Rect(b))
                    }
                }
            }
            return true
        }

        private fun abs(f: Float) = if (f < 0) -f else f
    }

    init {
        root.addView(board, FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT))
        val bar = LinearLayout(context).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            background = GradientDrawable().apply { cornerRadius = 22 * dp; setColor(0xF2202124.toInt()) }
            elevation = 10 * dp
            addView(TextView(context).apply {
                text = context.getString(R.string.subtitle_pick_hint)
                setTextColor(0xCCFFFFFF.toInt())
                setTextSize(TypedValue.COMPLEX_UNIT_SP, 14f)
                setPadding((16 * dp).toInt(), 0, (8 * dp).toInt(), 0)
            })
            if (last != null) addView(button(context.getString(R.string.subtitle_use_last)) { onPicked(Rect(last)) })
            addView(button("✕") { onCancel() })
        }
        root.addView(bar, FrameLayout.LayoutParams(
            FrameLayout.LayoutParams.WRAP_CONTENT, FrameLayout.LayoutParams.WRAP_CONTENT,
            Gravity.TOP or Gravity.CENTER_HORIZONTAL,
        ).apply { topMargin = topInset + (12 * dp).toInt() })
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

    fun attach() {
        runCatching { wm.addView(root, overlayParams(screen, touchable = true, focusable = true)) }.onSuccess {
            attached = true
            root.isFocusableInTouchMode = true
            root.requestFocus()
        }
    }

    fun detach() {
        if (!attached) return
        attached = false
        runCatching { wm.removeView(root) }
    }
}

/**
 * "Video subtitles", step 2: the translation of whatever is in the box,
 * centred, right under the original subtitle (above it when there's no room
 * below). It never covers the box, so the box can be read again and again
 * with the translation on screen — no hiding it for screenshots, no flicker —
 * and the original stays visible. Touches go straight through to the video.
 */
@SuppressLint("ViewConstructor")
class SubtitleOverlay(
    private val context: Context,
    private val wm: WindowManager,
    private val screen: Rect,
    private val region: Rect,
) {
    private val dp = context.resources.displayMetrics.density
    private val root = FrameLayout(context)
    private val outline = object : View(context) {
        private val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            style = Paint.Style.STROKE
            strokeWidth = 1.5f * dp
            color = 0xAAFFFFFF.toInt()
            pathEffect = DashPathEffect(floatArrayOf(8 * dp, 6 * dp), 0f)
        }

        override fun onDraw(canvas: Canvas) {
            canvas.drawRoundRect(RectF(1f, 1f, width - 1f, height - 1f), 6 * dp, 6 * dp, paint)
        }
    }
    private val text = TextView(context).apply {
        setTextColor(Color.WHITE)
        gravity = Gravity.CENTER
        textAlignment = View.TEXT_ALIGNMENT_CENTER
        maxLines = 3
        ellipsize = TextUtils.TruncateAt.END
        setPadding((10 * dp).toInt(), (4 * dp).toInt(), (10 * dp).toInt(), (4 * dp).toInt())
        background = GradientDrawable().apply { cornerRadius = 6 * dp; setColor(0xD9000000.toInt()) }
        setShadowLayer(2 * dp, 0f, 0f, Color.BLACK)
        visibility = View.GONE
    }
    private var attached = false

    private val gap = (4 * dp).toInt()

    init {
        // Drawn just outside the box, so OCR of the box never sees it.
        val o = (3 * dp).toInt()
        root.addView(outline, FrameLayout.LayoutParams(region.width() + 2 * o, region.height() + 2 * o).apply {
            leftMargin = region.left - o; topMargin = region.top - o
        })
        // As wide as the box (at least 60% of the screen), centred on it.
        val w = maxOf(region.width(), (screen.width() * 0.6f).toInt()).coerceAtMost(screen.width())
        val left = (region.centerX() - w / 2).coerceIn(0, screen.width() - w)
        root.addView(text, FrameLayout.LayoutParams(w, FrameLayout.LayoutParams.WRAP_CONTENT).apply {
            leftMargin = left; topMargin = region.bottom + gap
        })
    }

    fun attach() {
        runCatching { wm.addView(root, overlayParams(screen, touchable = false, focusable = false)) }.onSuccess {
            attached = true
            // The dashed box says "watching here", then gets out of the way.
            outline.animate().alpha(0f).setStartDelay(2500).setDuration(400).start()
        }
    }

    fun detach() {
        if (!attached) return
        attached = false
        runCatching { wm.removeView(root) }
    }

    /** [fontPx]: the original subtitle's size (from OCR), so the translation reads the same. */
    fun show(translation: String, fontPx: Float?) {
        val px = (fontPx ?: (16 * dp)).coerceIn(13 * dp, 26 * dp)
        text.setTextSize(TypedValue.COMPLEX_UNIT_PX, px)
        text.text = translation
        text.visibility = View.VISIBLE
        text.post { keepOnScreen() }
    }

    fun clear() {
        text.visibility = View.GONE
        text.text = ""
    }

    /** Below the box if it fits, else above it — never over it. */
    private fun keepOnScreen() {
        val lp = text.layoutParams as FrameLayout.LayoutParams
        val below = region.bottom + gap
        lp.topMargin = if (below + text.height <= screen.height()) below
        else (region.top - gap - text.height).coerceAtLeast(0)
        text.layoutParams = lp
    }
}
