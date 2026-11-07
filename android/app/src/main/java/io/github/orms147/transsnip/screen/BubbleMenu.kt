package io.github.orms147.transsnip.screen

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.Rect
import android.graphics.drawable.GradientDrawable
import android.util.TypedValue
import android.view.Gravity
import android.view.MotionEvent
import android.view.WindowManager
import android.widget.LinearLayout
import android.widget.TextView

/**
 * Small menu next to the bubble (hold the bubble): what you can do with
 * TransSnip right there, including turning it off. A touch anywhere outside
 * closes it.
 */
class BubbleMenu(private val context: Context, private val wm: WindowManager) {

    class Item(val label: String, val action: () -> Unit)

    private val dp = context.resources.displayMetrics.density
    private var view: LinearLayout? = null

    val isShown get() = view != null

    /** [anchor]: the bubble's box on screen — the menu opens beside it, on the roomy side. */
    @SuppressLint("ClickableViewAccessibility")
    fun show(anchor: Rect, screen: Rect, items: List<Item>) {
        dismiss()
        val panel = LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL
            setPadding((6 * dp).toInt(), (6 * dp).toInt(), (6 * dp).toInt(), (6 * dp).toInt())
            background = GradientDrawable().apply {
                cornerRadius = 16 * dp
                setColor(0xF2202124.toInt())
            }
            elevation = 10 * dp
            // FLAG_WATCH_OUTSIDE_TOUCH: a touch elsewhere arrives as ACTION_OUTSIDE.
            setOnTouchListener { _, e ->
                if (e.actionMasked == MotionEvent.ACTION_OUTSIDE) { dismiss(); true } else false
            }
        }
        for (item in items) {
            panel.addView(TextView(context).apply {
                text = item.label
                setTextColor(Color.WHITE)
                setTextSize(TypedValue.COMPLEX_UNIT_SP, 15f)
                gravity = Gravity.CENTER_VERTICAL
                minHeight = (44 * dp).toInt()
                setPadding((14 * dp).toInt(), 0, (18 * dp).toInt(), 0)
                background = context.getDrawable(android.R.drawable.list_selector_background)
                setOnClickListener {
                    dismiss()
                    item.action()
                }
            })
        }
        val lp = WindowManager.LayoutParams(
            WindowManager.LayoutParams.WRAP_CONTENT, WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_WATCH_OUTSIDE_TOUCH or
                WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
            PixelFormat.TRANSLUCENT,
        ).apply {
            gravity = Gravity.TOP or Gravity.START
            panel.measure(0, 0)
            val w = panel.measuredWidth
            val h = panel.measuredHeight
            val gap = (8 * dp).toInt()
            x = if (anchor.centerX() > screen.centerX()) anchor.left - w - gap else anchor.right + gap
            y = (anchor.centerY() - h / 2).coerceIn((24 * dp).toInt(), (screen.bottom - h - (24 * dp).toInt()).coerceAtLeast(0))
            x = x.coerceIn(0, (screen.right - w).coerceAtLeast(0))
        }
        runCatching { wm.addView(panel, lp) }.onSuccess { view = panel }
    }

    fun dismiss() {
        view?.let { runCatching { wm.removeView(it) } }
        view = null
    }
}
