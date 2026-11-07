package io.github.orms147.transsnip.screen

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.Rect
import android.graphics.drawable.GradientDrawable
import android.os.SystemClock
import android.util.TypedValue
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.ViewConfiguration
import android.view.WindowManager
import android.widget.TextView
import io.github.orms147.transsnip.AppSettings
import io.github.orms147.transsnip.R
import kotlin.math.abs

/**
 * Draggable floating button. Tap → translate the screen; long-press → hide it
 * (turn it back on in TransSnip's settings). Snaps to the nearest side edge
 * and remembers where it was left.
 */
class Bubble(
    context: Context,
    private val wm: WindowManager,
    private val settings: AppSettings,
    private val screen: () -> Rect,
    private val onTap: () -> Unit,
    private val onLongPress: () -> Unit,
) {
    private val dp = context.resources.displayMetrics.density
    private val size = (48 * dp).toInt()
    private val view = TextView(context).apply {
        text = "译"
        setTextColor(Color.WHITE)
        setTextSize(TypedValue.COMPLEX_UNIT_SP, 20f)
        gravity = Gravity.CENTER
        background = GradientDrawable().apply {
            shape = GradientDrawable.OVAL
            setColor(context.getColor(R.color.accent))
            setStroke((2 * dp).toInt(), 0x66FFFFFF)
        }
        elevation = 6 * dp
        alpha = 0.92f
        contentDescription = "TransSnip — dịch màn hình"
    }
    private val lp = WindowManager.LayoutParams(
        size, size,
        WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
        WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
        PixelFormat.TRANSLUCENT,
    ).apply { gravity = Gravity.TOP or Gravity.START }
    private var shown = false

    init {
        val touchSlop = ViewConfiguration.get(context).scaledTouchSlop
        val longPress = ViewConfiguration.getLongPressTimeout().toLong()
        var downX = 0f
        var downY = 0f
        var startX = 0
        var startY = 0
        var downAt = 0L
        var dragging = false
        view.setOnTouchListener(@SuppressLint("ClickableViewAccessibility") { _, e ->
            when (e.actionMasked) {
                MotionEvent.ACTION_DOWN -> {
                    downX = e.rawX; downY = e.rawY
                    startX = lp.x; startY = lp.y
                    downAt = SystemClock.uptimeMillis()
                    dragging = false
                }
                MotionEvent.ACTION_MOVE -> {
                    val dx = e.rawX - downX
                    val dy = e.rawY - downY
                    if (!dragging && (abs(dx) > touchSlop || abs(dy) > touchSlop)) dragging = true
                    if (dragging) {
                        lp.x = (startX + dx).toInt()
                        lp.y = (startY + dy).toInt()
                        wm.updateViewLayout(view, lp)
                    }
                }
                MotionEvent.ACTION_UP -> {
                    if (dragging) snap()
                    else if (SystemClock.uptimeMillis() - downAt >= longPress) onLongPress()
                    else onTap()
                }
            }
            true
        })
    }

    fun show() {
        if (shown) {
            view.visibility = View.VISIBLE
            return
        }
        val s = screen()
        lp.x = settings.bubbleX.takeIf { it >= 0 } ?: (s.right - size - (4 * dp).toInt())
        lp.y = settings.bubbleY.takeIf { it >= 0 } ?: (s.height() * 0.4).toInt()
        clamp(s)
        wm.addView(view, lp)
        shown = true
    }

    /** Out of the way (and out of the screenshot) while translating. */
    fun hide() {
        if (shown) view.visibility = View.GONE
    }

    fun remove() {
        if (shown) runCatching { wm.removeView(view) }
        shown = false
    }

    private fun snap() {
        val s = screen()
        val margin = (4 * dp).toInt()
        lp.x = if (lp.x + size / 2 < s.centerX()) margin else s.right - size - margin
        clamp(s)
        wm.updateViewLayout(view, lp)
        settings.bubbleX = lp.x
        settings.bubbleY = lp.y
    }

    private fun clamp(s: Rect) {
        lp.x = lp.x.coerceIn(0, (s.right - size).coerceAtLeast(0))
        lp.y = lp.y.coerceIn((24 * dp).toInt(), (s.bottom - size - (24 * dp).toInt()).coerceAtLeast(0))
    }
}
