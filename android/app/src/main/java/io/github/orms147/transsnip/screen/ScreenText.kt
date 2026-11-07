package io.github.orms147.transsnip.screen

import android.accessibilityservice.AccessibilityService
import android.graphics.Rect
import android.graphics.RectF
import android.os.Build
import android.os.Bundle
import android.view.accessibility.AccessibilityNodeInfo
import android.view.accessibility.AccessibilityWindowInfo

/**
 * A piece of text on screen and where it is, in screen pixels.
 * [fontPx]: the original text size when the app told us (null → estimate).
 */
data class ScreenItem(val text: String, val bounds: Rect, val fontPx: Float? = null)

/**
 * Reads the text other apps already expose to accessibility services: exact
 * characters and their on-screen boxes, in a few tens of milliseconds, with no
 * OCR. Views that draw text themselves (video, images, games) expose nothing —
 * those go through OCR instead.
 */
object ScreenText {

    fun collect(service: AccessibilityService, screen: Rect): List<ScreenItem> {
        val own = service.packageName
        val roots = try {
            service.windows
                .filter { it.type == AccessibilityWindowInfo.TYPE_APPLICATION }
                .mapNotNull { it.root }
        } catch (_: Exception) {
            emptyList()
        }.ifEmpty { listOfNotNull(service.rootInActiveWindow) }

        val out = ArrayList<ScreenItem>()
        for (root in roots) walk(root, own, screen, out, 0)
        return dedupe(out)
    }

    private fun walk(node: AccessibilityNodeInfo, own: String, screen: Rect, out: MutableList<ScreenItem>, depth: Int) {
        if (depth > 80 || !node.isVisibleToUser) return
        if (node.packageName?.toString() == own) return
        val raw = node.text?.toString()?.trim()
        if (!raw.isNullOrEmpty() && !node.isPassword) {
            val r = Rect()
            node.getBoundsInScreen(r)
            if (r.intersect(screen) && r.width() > 6 && r.height() > 6) {
                val (tight, font) = glyphBox(node, raw, r)
                out += ScreenItem(clean(raw), tight ?: r, font)
                return   // a TextView's children (if any) repeat its text
            }
        }
        for (i in 0 until node.childCount) {
            val child = node.getChild(i) ?: continue
            walk(child, own, screen, out, depth + 1)
        }
    }

    /**
     * Where the characters actually are, from the per-character boxes a
     * TextView reports (API 26+): the view's bounds are often much bigger
     * than its text (a button with an icon, centred text, padding). Also gives
     * the real font size: a character box (one line's height, spacing
     * included) is about 1.3 × the text size. The tallest box is used —
     * characters cut off at a screen edge report only their visible part.
     * Only the visible part counts — a scrolled TextView reports every char.
     */
    private fun glyphBox(node: AccessibilityNodeInfo, text: String, view: Rect): Pair<Rect?, Float?> {
        val key = AccessibilityNodeInfo.EXTRA_DATA_TEXT_CHARACTER_LOCATION_KEY
        if (key !in node.availableExtraData) return null to null
        return try {
            val n = minOf(text.length, MAX_CHARS)
            val args = Bundle().apply {
                putInt(AccessibilityNodeInfo.EXTRA_DATA_TEXT_CHARACTER_LOCATION_ARG_START_INDEX, 0)
                putInt(AccessibilityNodeInfo.EXTRA_DATA_TEXT_CHARACTER_LOCATION_ARG_LENGTH, n)
            }
            if (!node.refreshWithExtraData(key, args)) return null to null
            val boxes = if (Build.VERSION.SDK_INT >= 33) {
                node.extras.getParcelableArray(key, RectF::class.java)
            } else {
                @Suppress("DEPRECATION")
                node.extras.getParcelableArray(key)?.filterIsInstance<RectF>()?.toTypedArray()
            } ?: return null to null
            val visible = boxes.filterNotNull().filter { it.width() > 0 && it.height() > 0 }
                .map { Rect(it.left.toInt(), it.top.toInt(), it.right.toInt(), it.bottom.toInt()) }
                .filter { Rect.intersects(it, view) }
            if (visible.isEmpty()) return null to null
            val box = Rect(visible[0])
            visible.forEach { box.union(it) }
            box.intersect(view)
            box.inset(-PAD, -PAD)
            box to visible.maxOf { it.height() } / LINE_TO_FONT
        } catch (_: Exception) {
            null to null
        }
    }

    /** Labels apps add for screen readers ("…，按钮" = "…, button") aren't on screen. */
    private fun clean(text: String): String {
        var t = text
        for (suffix in A11Y_SUFFIXES) if (t.endsWith(suffix) && t.length > suffix.length) t = t.dropLast(suffix.length)
        return t.trimEnd(',', '，', ' ')
    }

    /** The same text at the same place reported by two windows/nodes → once. */
    private fun dedupe(items: List<ScreenItem>): List<ScreenItem> {
        val seen = HashSet<String>()
        return items.filter { seen.add("${it.text}@${it.bounds.flattenToString()}") }
    }

    private const val MAX_CHARS = 400
    private const val LINE_TO_FONT = 1.3f
    private const val PAD = 3
    private val A11Y_SUFFIXES = listOf("按钮", "，按钮", ",按钮", ", button", ", Button")
}
