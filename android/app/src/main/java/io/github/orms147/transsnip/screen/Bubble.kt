package io.github.orms147.transsnip.screen

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.Rect
import android.graphics.drawable.GradientDrawable
import android.os.Handler
import android.os.Looper
import android.util.TypedValue
import android.view.Gravity
import android.view.HapticFeedbackConstants
import android.view.MotionEvent
import android.view.View
import android.view.ViewConfiguration
import android.view.WindowManager
import android.widget.TextView
import io.github.orms147.transsnip.AppSettings
import io.github.orms147.transsnip.R
import kotlin.math.abs
import kotlin.math.hypot

/**
 * Draggable floating button, like a chat head:
 *  - tap → translate the screen (while translations are showing it turns
 *    into ✕ and a tap closes them);
 *  - drag → move; it snaps to the nearest side and remembers the spot;
 *    drop it on the ✕ target at the bottom → hide it;
 *  - idle for a few seconds → fades back so it doesn't sit on content.
 */
class Bubble(
    context: Context,
    private val wm: WindowManager,
    private val settings: AppSettings,
    private val screen: () -> Rect,
    private val onTap: () -> Unit,
    private val onDropOnClose: () -> Unit,
    private val onLongPress: () -> Unit,
) {
    private val dp = context.resources.displayMetrics.density
    private val size = (48 * dp).toInt()
    private val accent = context.getColor(R.color.accent)
    private val main = Handler(Looper.getMainLooper())
    private val fade = Runnable { if (!active) view.animate().alpha(IDLE_ALPHA).setDuration(400).start() }

    private val view = TextView(context).apply {
        setTextColor(Color.WHITE)
        setTextSize(TypedValue.COMPLEX_UNIT_SP, 20f)
        gravity = Gravity.CENTER
        elevation = 6 * dp
        contentDescription = context.getString(R.string.bubble_desc)
    }
    private val lp = params(size, size)

    // The ✕ drop target shown while dragging.
    private val target = TextView(context).apply {
        text = "✕"
        setTextColor(Color.WHITE)
        setTextSize(TypedValue.COMPLEX_UNIT_SP, 22f)
        gravity = Gravity.CENTER
        background = GradientDrawable().apply {
            shape = GradientDrawable.OVAL
            setColor(0xCC202124.toInt())
            setStroke((2 * dp).toInt(), 0x88FFFFFF.toInt())
        }
    }
    private val targetSize = (64 * dp).toInt()
    private val targetLp = params(targetSize, targetSize).apply {
        flags = flags or WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE
    }
    private var targetShown = false
    private var overTarget = false

    private var shown = false
    private var active = false
    private var lookup = false
    private var longFired = false
    private val longPress = Runnable {
        longFired = true
        view.performHapticFeedback(HapticFeedbackConstants.LONG_PRESS)
        onLongPress()
    }

    init {
        paint()
        val touchSlop = ViewConfiguration.get(context).scaledTouchSlop
        var downX = 0f
        var downY = 0f
        var startX = 0
        var startY = 0
        var dragging = false
        view.setOnTouchListener(@SuppressLint("ClickableViewAccessibility") { _, e ->
            when (e.actionMasked) {
                MotionEvent.ACTION_DOWN -> {
                    wake()
                    downX = e.rawX; downY = e.rawY
                    startX = lp.x; startY = lp.y
                    dragging = false
                    longFired = false
                    main.postDelayed(longPress, ViewConfiguration.getLongPressTimeout().toLong())
                }
                MotionEvent.ACTION_MOVE -> {
                    val dx = e.rawX - downX
                    val dy = e.rawY - downY
                    if (!dragging && (abs(dx) > touchSlop || abs(dy) > touchSlop)) {
                        dragging = true
                        main.removeCallbacks(longPress)
                        showTarget()
                    }
                    if (dragging) {
                        lp.x = (startX + dx).toInt()
                        lp.y = (startY + dy).toInt()
                        val near = nearTarget()
                        if (near != overTarget) {
                            overTarget = near
                            view.performHapticFeedback(HapticFeedbackConstants.VIRTUAL_KEY)
                            target.animate().scaleX(if (near) 1.25f else 1f).scaleY(if (near) 1.25f else 1f)
                                .setDuration(120).start()
                        }
                        wm.updateViewLayout(view, lp)
                    }
                }
                MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                    main.removeCallbacks(longPress)
                    if (longFired) {
                        // handled when the press became long
                    } else if (dragging) {
                        hideTarget()
                        if (overTarget) {
                            overTarget = false
                            onDropOnClose()
                        } else {
                            snap()
                        }
                    } else if (e.actionMasked == MotionEvent.ACTION_UP) {
                        view.performHapticFeedback(HapticFeedbackConstants.VIRTUAL_KEY)
                        onTap()
                    }
                    sleepLater()
                }
            }
            true
        })
    }

    private fun params(w: Int, h: Int) = WindowManager.LayoutParams(
        w, h,
        WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
        WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
        PixelFormat.TRANSLUCENT,
    ).apply { gravity = Gravity.TOP or Gravity.START }

    /** Translations on screen: the bubble becomes their close button. */
    fun setActive(on: Boolean, lookUp: Boolean = false) {
        active = on
        lookup = on && lookUp
        paint()
        wake()
        sleepLater()
    }

    private fun paint() {
        view.text = if (active) "✕" else "译"
        view.background = GradientDrawable().apply {
            shape = GradientDrawable.OVAL
            // Look-up mode: the ✕ turns accent-coloured — touches go to the boxes now.
            setColor(if (active && !lookup) 0xF0202124.toInt() else accent)
            setStroke((2 * dp).toInt(), 0x66FFFFFF)
        }
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
        sleepLater()
    }

    /** Out of the way (and out of the screenshot) while capturing. */
    fun hide() {
        if (shown) view.visibility = View.GONE
    }

    /** Windows of one type stack in the order they were added: re-add to sit above the overlay. */
    fun bringToFront() {
        if (!shown) return
        runCatching { wm.removeView(view) }
        runCatching { wm.addView(view, lp) }
        view.visibility = View.VISIBLE
    }

    /** Where the bubble is on screen (to open the menu beside it). */
    fun bounds(): Rect = Rect(lp.x, lp.y, lp.x + size, lp.y + size)

    fun remove() {
        main.removeCallbacks(fade)
        hideTarget()
        if (shown) runCatching { wm.removeView(view) }
        shown = false
    }

    private fun wake() {
        main.removeCallbacks(fade)
        view.animate().cancel()
        view.alpha = 1f
    }

    private fun sleepLater() {
        main.removeCallbacks(fade)
        main.postDelayed(fade, 3000)
    }

    private fun showTarget() {
        if (targetShown) return
        val s = screen()
        targetLp.x = s.centerX() - targetSize / 2
        targetLp.y = s.bottom - targetSize - (96 * dp).toInt()
        target.scaleX = 1f
        target.scaleY = 1f
        target.alpha = 0f
        runCatching { wm.addView(target, targetLp) }
        targetShown = true
        target.animate().alpha(1f).setDuration(150).start()
    }

    private fun hideTarget() {
        if (!targetShown) return
        targetShown = false
        runCatching { wm.removeView(target) }
    }

    private fun nearTarget(): Boolean {
        val cx = lp.x + size / 2f
        val cy = lp.y + size / 2f
        val tx = targetLp.x + targetSize / 2f
        val ty = targetLp.y + targetSize / 2f
        return hypot(cx - tx, cy - ty) < 72 * dp
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

    companion object {
        private const val IDLE_ALPHA = 0.45f
    }
}
