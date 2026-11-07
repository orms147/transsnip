package io.github.orms147.transsnip.screen

import android.accessibilityservice.AccessibilityService
import android.graphics.Rect
import android.view.accessibility.AccessibilityNodeInfo
import android.view.accessibility.AccessibilityWindowInfo

/** A piece of text on screen and where it is, in screen pixels. */
data class ScreenItem(val text: String, val bounds: Rect)

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
        val text = node.text?.toString()?.trim()
        if (!text.isNullOrEmpty() && !node.isPassword) {
            val r = Rect()
            node.getBoundsInScreen(r)
            if (r.intersect(screen) && r.width() > 6 && r.height() > 6) {
                out += ScreenItem(text, r)
                return   // a TextView's children (if any) repeat its text
            }
        }
        for (i in 0 until node.childCount) {
            val child = node.getChild(i) ?: continue
            walk(child, own, screen, out, depth + 1)
        }
    }

    /** The same text at the same place reported by two windows/nodes → once. */
    private fun dedupe(items: List<ScreenItem>): List<ScreenItem> {
        val seen = HashSet<String>()
        return items.filter { seen.add("${it.text}@${it.bounds.flattenToString()}") }
    }
}
