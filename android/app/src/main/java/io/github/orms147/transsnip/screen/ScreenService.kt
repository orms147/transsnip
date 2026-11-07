package io.github.orms147.transsnip.screen

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.graphics.Path
import android.graphics.PointF
import android.content.Intent
import android.content.SharedPreferences
import android.graphics.Bitmap
import android.graphics.Rect
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.util.DisplayMetrics
import android.view.Display
import android.view.WindowManager
import android.view.accessibility.AccessibilityEvent
import android.widget.Toast
import io.github.orms147.transsnip.AppSettings
import io.github.orms147.transsnip.BuildConfig
import io.github.orms147.transsnip.MainActivity
import io.github.orms147.transsnip.R
import io.github.orms147.transsnip.TranslateActivity
import io.github.orms147.transsnip.translate.BatchTranslator
import io.github.orms147.transsnip.translate.OpenRouterClient
import io.github.orms147.transsnip.translate.Prompts
import io.github.orms147.transsnip.translate.Translator
import java.util.concurrent.Executors

/**
 * Screen translation. Tapping the floating bubble:
 *  1. reads the text other apps expose to accessibility (exact, ~30 ms) —
 *     or, when there is none (video, images, games), OCRs a screenshot;
 *  2. sends every line to the model in ONE streamed request (plus a cache, so
 *     scrolling back costs nothing);
 *  3. paints a box with the translation over each piece of text.
 *
 * Accessibility also gives screenshots (Android 11+) without the per-session
 * "start recording?" consent that MediaProjection needs.
 */
class ScreenService : AccessibilityService() {

    private val main = Handler(Looper.getMainLooper())
    private val pool = Executors.newCachedThreadPool()   // a dismissed run never blocks the next one
    private lateinit var settings: AppSettings
    private lateinit var wm: WindowManager
    private var bubble: Bubble? = null
    private var session: Session? = null
    private var generation = 0
    private val cache = object : LinkedHashMap<String, String>(256, 0.75f, true) {
        override fun removeEldestEntry(eldest: MutableMap.MutableEntry<String, String>?) = size > 800
    }
    // Held in a field: SharedPreferences keeps only a weak reference.
    private val prefListener = SharedPreferences.OnSharedPreferenceChangeListener { _, key ->
        when (key) {
            AppSettings.KEY_BUBBLE -> syncBubble()
            "api_key" -> warmUp()
        }
    }

    private val recapture = Runnable { if (session == null) start(delay = 0) }
    private var awaitingScroll = false

    override fun onServiceConnected() {
        instance = this
        settings = AppSettings(this)
        wm = getSystemService(WindowManager::class.java)
        settings.onChange(prefListener)
        syncBubble()
        warmUp()
        pool.execute { Ocr.warmUp() }
    }

    /**
     * After a swipe was replayed on the app, wait for its scrolling (incl.
     * fling) to stop: every scroll event pushes the re-translation back a bit.
     */
    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        if (!awaitingScroll || event?.eventType != AccessibilityEvent.TYPE_VIEW_SCROLLED) return
        main.removeCallbacks(recapture)
        main.postDelayed(recapture, SCROLL_QUIET_MS)
    }

    override fun onInterrupt() {}

    override fun onDestroy() {
        if (instance === this) instance = null
        if (::settings.isInitialized) {
            dismiss(showBubble = false)
            bubble?.remove()
            settings.offChange(prefListener)
        }
        pool.shutdownNow()
        super.onDestroy()
    }

    private fun syncBubble() {
        if (settings.bubble) {
            val b = bubble ?: Bubble(this, wm, settings, ::screenRect, ::onBubbleTap, ::onBubbleDropped)
                .also { bubble = it }
            if (session == null && ownUi == 0) b.show()
        } else {
            bubble?.remove()
            bubble = null
        }
    }

    private fun warmUp() {
        val key = settings.apiKey ?: return
        pool.execute { OpenRouterClient.warmUp(key, connections = 4) }
    }

    private fun onBubbleDropped() {
        settings.bubble = false
        Toast.makeText(this, R.string.bubble_hidden, Toast.LENGTH_LONG).show()
    }

    private fun onBubbleTap() {
        if (session != null) dismiss() else start()
    }

    private fun onOwnUiChanged() {
        if (ownUi > 0) bubble?.hide() else if (session == null) bubble?.show()
    }

    /** Quick Settings tile: close the shade first — it must not be in the screenshot. */
    fun translateFromTile() {
        if (session != null) dismiss()
        if (Build.VERSION.SDK_INT >= 31) performGlobalAction(GLOBAL_ACTION_DISMISS_NOTIFICATION_SHADE)
        start(delay = 450)
    }

    private fun start(delay: Long = 50) {
        awaitingScroll = false
        main.removeCallbacks(recapture)
        val key = settings.apiKey
        if (key.isNullOrBlank()) {
            Toast.makeText(this, R.string.err_no_key, Toast.LENGTH_LONG).show()
            startActivity(Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            return
        }
        bubble?.hide()
        val gen = ++generation
        // One frame for the bubble to leave the screen before the screenshot.
        main.postDelayed({ if (gen == generation) capture(gen, key) }, delay.coerceAtLeast(16))
    }

    private fun capture(gen: Int, key: String) {
        val started = SystemClock.uptimeMillis()
        val screen = screenRect()
        val target = settings.targetLang
        val exposed = ScreenText.collect(this, screen)
        val items = exposed.filter { Prompts.needsTranslation(it.text, target) }
        if (BuildConfig.DEBUG) exposed.forEach {
            android.util.Log.v("TransSnipItems", "${it.bounds.toShortString()} font=${it.fontPx} ${it.text.take(40).replace('\n', '|')}")
        }
        val overlay = ScreenOverlay(this, wm, screen, ::openBox, { dismiss() }, ::onSwipe)
        val s = Session(gen, overlay, started)
        session = s
        overlay.setStatus(getString(R.string.screen_working))
        // Two waves: the exposed text goes out right now; OCR of the
        // screenshot then adds what only exists as pixels (video, images).
        s.waves = if (items.isNotEmpty()) 2 else 1
        if (items.isNotEmpty()) translate(s, key, s.add(items))
        takeScreenshot { shot ->
            if (gen != generation) return@takeScreenshot
            overlay.attach()
            bubble?.setActive(true)
            if (ownUi == 0) bubble?.bringToFront()   // the ✕ sits above the overlay
            s.shot = shot
            s.showBoxes(s.items.indices)
            if (shot == null) return@takeScreenshot s.waveDone(null)
            if (items.isEmpty()) overlay.setStatus(getString(R.string.screen_ocr))
            ocr(s, key, shot, exposed.map { it.bounds })
        }
    }

    private fun ocr(s: Session, key: String, shot: Bitmap, exposed: List<Rect>) {
        val target = settings.targetLang
        val pad = (4 * resources.displayMetrics.density).toInt()
        pool.execute {
            val t0 = SystemClock.uptimeMillis()
            val found = runCatching { Ocr.recognize(shot, pad) }
            if (BuildConfig.DEBUG) android.util.Log.d("TransSnip", "ocr: ${SystemClock.uptimeMillis() - t0} ms, " +
                "${found.getOrNull()?.blocks?.size} blocks")
            post(s) {
                // Text accessibility already gave us (translated or not) is
                // skipped: exact characters beat OCR, and it isn't drawn twice.
                val ocr = found.getOrNull()
                // Apps that draw their own text (Douyin…) give no font size and
                // loose bounds: the OCR lines inside an item show both.
                if (ocr != null) s.refineFrom(ocr.lines)
                // The status bar (clock, icons) is in the screenshot too — never translate it.
                val statusBar = resources.getIdentifier("status_bar_height", "dimen", "android")
                    .takeIf { it != 0 }?.let { resources.getDimensionPixelSize(it) } ?: 0
                val extra = ocr?.blocks.orEmpty().filter { item ->
                    item.bounds.centerY() > statusBar &&
                        Prompts.needsTranslation(item.text, target) && exposed.none { overlap(item.bounds, it) > 0.3 }
                }
                val range = s.add(extra)
                s.showBoxes(range)
                s.shot = null
                shot.recycle()
                if (range.isEmpty()) s.waveDone(found.exceptionOrNull()) else translate(s, key, range)
            }
        }
    }

    /** Share of [a]'s area covered by [b]. */
    private fun overlap(a: Rect, b: Rect): Double {
        val r = Rect()
        if (a.isEmpty || !r.setIntersect(a, b)) return 0.0
        return r.width().toDouble() * r.height() / (a.width().toDouble() * a.height())
    }

    private fun translate(s: Session, key: String, range: IntRange) {
        val target = settings.targetLang
        val model = settings.model
        val lines = s.linesToTranslate(range, target)
        val sent = SystemClock.uptimeMillis()
        pool.execute {
            fun ck(line: String) = "$model|$target|$line"
            val fresh = ArrayList<String>()
            for (line in lines) {
                val hit = synchronized(cache) { cache[ck(line)] }
                if (hit != null) post(s) { s.deliver(line, hit) } else fresh += line
            }
            var first = 0L
            val error = runCatching {
                BatchTranslator(OpenRouterClient(key, model), Translator.minimalFirst(model))
                    .translate(fresh, target) { i, t ->
                        if (first == 0L) first = SystemClock.uptimeMillis()
                        synchronized(cache) { cache[ck(fresh[i])] = t }
                        post(s) { s.deliver(fresh[i], t) }
                    }
            }.exceptionOrNull()
            if (BuildConfig.DEBUG) {
                val now = SystemClock.uptimeMillis()
                android.util.Log.d("TransSnip", "screen: ${lines.size} lines (${fresh.size} new), " +
                    "request→first line ${if (first > 0) first - sent else -1} ms, total ${now - sent} ms, " +
                    "since tap ${now - s.started} ms, error=${error?.message}")
            }
            post(s) { s.waveDone(error) }
        }
    }

    private fun openBox(i: Int) {
        val s = session ?: return
        val item = s.items.getOrNull(i) ?: return
        val translation = if (s.isTranslated(i)) s.composed(i) else ""
        dismiss()
        startActivity(
            Intent(this, TranslateActivity::class.java)
                .setAction(Intent.ACTION_SEND)
                .setType("text/plain")
                .putExtra(Intent.EXTRA_TEXT, item.text)
                .putExtra(TranslateActivity.EXTRA_TRANSLATION, translation)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
        )
    }

    private fun dismiss(showBubble: Boolean = true) {
        generation++
        awaitingScroll = false
        main.removeCallbacks(recapture)
        session?.overlay?.detach()
        session = null
        bubble?.setActive(false)
        if (showBubble && ownUi == 0) bubble?.show()
    }

    /**
     * A swipe on the overlay: drop the (now stale) translations, replay the
     * same stroke on the app underneath so the page really scrolls, and
     * translate again once it stops moving. Lines seen before come from the
     * cache, so scrolling back and forth reads like a translated page.
     */
    private fun onSwipe(points: List<PointF>, durationMs: Long) {
        if (session == null) return
        generation++
        session?.overlay?.detach()
        session = null
        bubble?.hide()
        if (points.size < 2) return start(delay = 0)
        val path = Path().apply {
            moveTo(points[0].x, points[0].y)
            for (p in points.drop(1)) lineTo(p.x, p.y)
        }
        val stroke = GestureDescription.StrokeDescription(path, 0, durationMs.coerceIn(50, 2000))
        val gen = generation
        val settle = {
            if (gen == generation && session == null) {
                awaitingScroll = true
                main.removeCallbacks(recapture)
                main.postDelayed(recapture, SCROLL_START_MS)
            }
        }
        // The overlay window must be gone from the window manager first, or
        // it swallows the replayed touch itself.
        main.postDelayed({
            if (gen != generation) return@postDelayed
            val sent = dispatchGesture(GestureDescription.Builder().addStroke(stroke).build(),
                object : GestureResultCallback() {
                    override fun onCompleted(gestureDescription: GestureDescription?) = settle()
                    override fun onCancelled(gestureDescription: GestureDescription?) {
                        if (BuildConfig.DEBUG) android.util.Log.d("TransSnip", "swipe replay cancelled")
                        settle()
                    }
                }, main)
            if (BuildConfig.DEBUG) android.util.Log.d("TransSnip", "swipe replay sent=$sent points=${points.size} ms=$durationMs")
            if (!sent) settle()
        }, GESTURE_DELAY_MS)
    }

    /** Runs [block] on the main thread unless that run was dismissed meanwhile. */
    private fun post(s: Session, block: () -> Unit) {
        main.post { if (s.gen == generation) block() }
    }

    companion object {
        /** The running service, for the Quick Settings tile and TransSnip's popups. */
        @Volatile
        var instance: ScreenService? = null
            private set

        /**
         * TransSnip popups currently open — the bubble stays off them. Kept
         * here, not in the service, so a popup opened while the service is
         * (re)starting still counts once it connects.
         */
        private var ownUi = 0

        fun ownUi(visible: Boolean) {
            ownUi = (ownUi + if (visible) 1 else -1).coerceAtLeast(0)
            instance?.onOwnUiChanged()
        }

        private const val SCROLL_START_MS = 450L   // no scroll event at all → content didn't move much
        private const val SCROLL_QUIET_MS = 250L
        private const val PAD_OCR = 6
        private const val GESTURE_DELAY_MS = 120L
    }

    private fun takeScreenshot(done: (Bitmap?) -> Unit) {
        if (Build.VERSION.SDK_INT < 30) return done(null)
        try {
            takeScreenshot(Display.DEFAULT_DISPLAY, mainExecutor, object : TakeScreenshotCallback {
                override fun onSuccess(result: ScreenshotResult) {
                    val bmp = runCatching {
                        Bitmap.wrapHardwareBuffer(result.hardwareBuffer, result.colorSpace)
                            ?.copy(Bitmap.Config.ARGB_8888, false)
                    }.getOrNull()
                    result.hardwareBuffer.close()
                    done(bmp)
                }

                override fun onFailure(errorCode: Int) = done(null)
            })
        } catch (_: Exception) {
            done(null)
        }
    }

    private fun screenRect(): Rect =
        if (Build.VERSION.SDK_INT >= 30) {
            Rect(wm.maximumWindowMetrics.bounds)
        } else {
            val m = DisplayMetrics()
            @Suppress("DEPRECATION")
            wm.defaultDisplay.getRealMetrics(m)
            Rect(0, 0, m.widthPixels, m.heightPixels)
        }

    /** One tap of the bubble: the items found, their lines, translations so far. Main thread only. */
    private inner class Session(val gen: Int, val overlay: ScreenOverlay, val started: Long) {
        val items = ArrayList<ScreenItem>()
        private val lines = ArrayList<List<String>>()
        private val translated = HashMap<String, String>()
        private val shown = HashSet<Int>()
        var shot: Bitmap? = null
        var waves = 0
        private var error: Throwable? = null
        private var hintShownThisRun = false

        fun add(list: List<ScreenItem>): IntRange {
            val from = items.size
            for (item in list) {
                items += item
                lines += item.text.split('\n').map(String::trim).filter(String::isNotEmpty)
            }
            return from until items.size
        }

        fun linesToTranslate(range: IntRange, target: String) =
            range.flatMap { lines[it] }.filter { Prompts.needsTranslation(it, target) && it !in translated }.distinct()

        fun showBoxes(range: IntRange) {
            for (i in range) {
                overlay.addBox(i, items[i].bounds, Colors.behind(shot, items[i].bounds), items[i].text, items[i].fontPx)
                shown += i
                refresh(i)
            }
        }

        fun refineFrom(ocrLines: List<Rect>) {
            for (i in shown) {
                val item = items[i]
                if (item.fontPx != null) continue
                val inside = ocrLines.filter { overlap(it, item.bounds) > 0.6 }
                if (inside.isEmpty()) continue
                val box = Rect(inside[0]).apply { inside.forEach { union(it) } }
                box.inset(-PAD_OCR, -PAD_OCR)
                box.intersect(item.bounds)
                val heights = inside.map { it.height() }.sorted()
                overlay.refine(i, box, heights[heights.size / 2] / Ocr.GLYPH_TO_FONT)
            }
        }

        fun deliver(line: String, translation: String) {
            translated[line] = translation
            for (i in shown) if (line in lines[i]) refresh(i)
        }

        fun isTranslated(i: Int) = lines[i].any { it in translated }
        fun composed(i: Int) = lines[i].joinToString("\n") { translated[it] ?: it }

        private fun refresh(i: Int) {
            if (isTranslated(i)) overlay.setText(i, composed(i))
        }

        /**
         * Reports as soon as there is something to show — OCR (seconds on a
         * busy phone) adds its boxes later without holding up "done".
         */
        fun waveDone(e: Throwable?) {
            if (e != null) error = e
            val last = --waves <= 0
            val ms = SystemClock.uptimeMillis() - started
            when {
                translated.isEmpty() && !last -> overlay.setStatus(getString(R.string.screen_ocr))
                items.isEmpty() -> overlay.setStatus(getString(R.string.screen_no_text), autoHideMs = 2500)
                translated.isEmpty() && error != null -> overlay.setStatus(getString(R.string.test_failed, error?.message))
                translated.isEmpty() -> overlay.setStatus(getString(R.string.screen_no_text), autoHideMs = 2500)
                hintShownThisRun -> overlay.setStatus(
                    getString(R.string.screen_done, shown.count { isTranslated(it) }, ms / 1000.0) + "\n" +
                        getString(R.string.screen_hint), autoHideMs = 5000)
                else -> {
                    val done = getString(R.string.screen_done, shown.count { isTranslated(it) }, ms / 1000.0)
                    // The gestures aren't discoverable: spell them out the first few times.
                    if (settings.hintsShown < 3) {
                        settings.hintsShown += 1
                        hintShownThisRun = true
                        overlay.setStatus(done + "\n" + getString(R.string.screen_hint), autoHideMs = 5000)
                    } else {
                        overlay.setStatus(done, autoHideMs = 1800)
                    }
                }
            }
        }
    }
}
