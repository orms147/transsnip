package io.github.orms147.transsnip.screen

import android.graphics.Bitmap
import com.google.android.gms.tasks.Tasks
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.text.TextRecognition
import com.google.mlkit.vision.text.chinese.ChineseTextRecognizerOptions
import java.util.concurrent.TimeUnit

/**
 * On-device OCR (ML Kit, Chinese model — it reads Latin script too) for
 * screens that expose no text: video, images, games. Bundled model: works
 * offline and on phones without Google Play services.
 */
object Ocr {
    private val recognizer by lazy {
        TextRecognition.getClient(ChineseTextRecognizerOptions.Builder().build())
    }

    /**
     * Blocking — call off the main thread. One item per text block (a paragraph/caption).
     * [pad]: OCR boxes hug the glyphs; grow them so the cover hides anti-aliased edges too.
     */
    fun recognize(bitmap: Bitmap, pad: Int = 0): List<ScreenItem> {
        val result = Tasks.await(recognizer.process(InputImage.fromBitmap(bitmap, 0)), 15, TimeUnit.SECONDS)
        return result.textBlocks.mapNotNull { block ->
            val box = block.boundingBox ?: return@mapNotNull null
            val lines = block.lines.map { it.text.trim() }.filter { it.isNotEmpty() }
            box.inset(-pad, -pad)
            if (lines.isEmpty()) null else ScreenItem(joinLines(lines), box)
        }
    }

    /** Loads the model (~2 s the first time) so the first real OCR doesn't pay for it. */
    fun warmUp() {
        runCatching { recognize(Bitmap.createBitmap(64, 64, Bitmap.Config.ARGB_8888)) }
    }

    /**
     * A wrapped Chinese sentence must be translated whole, so a block's lines
     * become one line: joined directly between Han characters, with a space
     * between Latin words.
     */
    fun joinLines(lines: List<String>): String = lines.reduce { acc, next ->
        val a = acc.last()
        val b = next.first()
        if (a.code >= 0x2E80 || b.code >= 0x2E80) acc + next else "$acc $next"
    }
}
