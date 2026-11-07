package io.github.orms147.transsnip.screen

import android.graphics.Bitmap
import android.graphics.Color
import android.graphics.Rect

object Colors {
    private const val FALLBACK = 0xF2FFFFFF.toInt()

    /**
     * The background a piece of text sits on: the most common colour among
     * points just inside and just outside its box corners (glyphs rarely reach
     * the corners). Quantised so anti-aliasing noise doesn't split the vote.
     */
    fun behind(shot: Bitmap?, r: Rect): Int {
        if (shot == null || shot.isRecycled) return FALLBACK
        val pts = listOf(
            r.left + 1 to r.top + 1, r.right - 2 to r.top + 1,
            r.left + 1 to r.bottom - 2, r.right - 2 to r.bottom - 2,
            r.left - 3 to r.top - 3, r.right + 2 to r.top - 3,
            r.left - 3 to r.bottom + 2, r.right + 2 to r.bottom + 2,
            r.centerX() to r.top + 1, r.centerX() to r.bottom - 2,
        )
        val votes = HashMap<Int, MutableList<Int>>()
        for ((x, y) in pts) {
            if (x < 0 || y < 0 || x >= shot.width || y >= shot.height) continue
            val c = shot.getPixel(x, y)
            val key = (Color.red(c) shr 4 shl 8) or (Color.green(c) shr 4 shl 4) or (Color.blue(c) shr 4)
            votes.getOrPut(key) { ArrayList() } += c
        }
        val best = votes.values.maxByOrNull { it.size } ?: return FALLBACK
        return best.first() or 0xFF000000.toInt()
    }
}
