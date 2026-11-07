package io.github.orms147.transsnip.screen

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.graphics.Path
import android.graphics.PointF
import android.content.ClipData
import android.content.ClipboardManager
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
            AppSettings.KEY_BUBBLE -> { syncBubble(); ScreenTile.refresh(this) }
            "api_key" -> warmUp()
        }
    }

    private val recapture = Runnable { if (session == null) start(delay = 0) }
    private var awaitingScroll = false
    private var live = false          // translations are on (✕ shows) — survives refreshes
    private var lookupField = false
    @set:JvmName("setLookupField")
    private var lookup: Boolean
        get() = lookupField
        set(v) { if (BuildConfig.DEBUG && v != lookupField) android.util.Log.d("TransSnipMode", "lookup=$v", Throwable()); lookupField = v }
    // ↑ lookup: still frame: screen frozen behind the boxes, overlay takes touches
    private var startedLive = true    // still frame entered from live mode (tap empty → back to live)
    private var livePkg: String? = null

    override fun onServiceConnected() {
        instance = this
        settings = AppSettings(this)
        main.post { stateListener?.invoke() }
        wm = getSystemService(WindowManager::class.java)
        settings.onChange(prefListener)
        syncBubble()
        warmUp()
        pool.execute { Ocr.warmUp() }
        // First run: say how to reach the menu (hide / turn off) — holding isn't discoverable.
        ScreenTile.refresh(this)
        if (settings.bubble && !settings.menuHintShown) {
            settings.menuHintShown = true
            Toast.makeText(this, R.string.bubble_first_hint, Toast.LENGTH_LONG).show()
        }
    }

    /**
     * After a swipe was replayed on the app, wait for its scrolling (incl.
     * fling) to stop: every scroll event pushes the re-translation back a bit.
     */
    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        val e = event ?: return
        val pkg = e.packageName?.toString()
        if (pkg == packageName) return
        if (awaitingScroll && e.eventType == AccessibilityEvent.TYPE_VIEW_SCROLLED) {
            main.removeCallbacks(recapture)
            main.postDelayed(recapture, SCROLL_QUIET_MS)
            return
        }
        if (!live || lookup) return
        when (e.eventType) {
            AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED -> {
                // Another app (or home) came up: translations of the old one are
                // meaningless. A keyboard or toast also sends this, from its own
                // package — so check which app is actually in front once it settles.
                if (pkg != null && pkg != livePkg) {
                    main.postDelayed({
                        if (!live) return@postDelayed
                        val front = rootInActiveWindow?.packageName?.toString()
                        if (front != null && front != livePkg && front != packageName) dismiss() else liveRefresh()
                    }, 300)
                    return
                }
                liveRefresh()
            }
            AccessibilityEvent.TYPE_VIEW_SCROLLED, AccessibilityEvent.TYPE_VIEW_CLICKED -> liveRefresh()
        }
    }

    /**
     * Live mode: touches go straight to the app. When it scrolls (or the user
     * taps something), the boxes are stale — fade them now, translate again
     * once the screen has been still for a moment (seen lines are cached).
     */
    private fun liveRefresh() {
        session?.overlay?.fadeOut()
        main.removeCallbacks(liveRecapture)
        main.postDelayed(liveRecapture, LIVE_QUIET_MS)
    }

    private val liveRecapture = Runnable {
        if (!live || lookup) return@Runnable
        val key = settings.apiKey ?: return@Runnable
        generation++
        session?.overlay?.detach()
        session = null
        val gen = ++generation
        main.postDelayed({ if (gen == generation) capture(gen, key, quiet = true) }, 16)
    }

    /** Hold ✕: still frame (read in peace, tap boxes) ↔ live (follows the screen, touches go to the app). */
    private fun setLookup(on: Boolean) {
        lookup = on
        if (on) main.removeCallbacks(liveRecapture)
        bubble?.setActive(live, on)
        val s = session ?: return
        s.overlay.setInteractive(on)
        s.overlay.setFrozen(if (on) s.frame else null)
        s.overlay.setStatus(getString(if (on) R.string.lookup_on else R.string.lookup_off), autoHideMs = 2500)
        if (!on) liveRefresh()   // the page may have changed while in look-up mode
    }

    private val menu by lazy { BubbleMenu(this, wm) }

    /**
     * Hold the bubble: while translating, toggle look-up mode; otherwise open
     * the menu — translate in look-up mode, hide the bubble, turn TransSnip
     * off, settings.
     */
    private fun onBubbleLongPress() {
        if (live) return setLookup(!lookup)
        val b = bubble ?: return
        menu.show(b.bounds(), screenRect(), listOf(
            BubbleMenu.Item(getString(R.string.menu_select)) { startSelect() },
            // The mode a tap doesn't start.
            if (settings.frozenDefault) BubbleMenu.Item(getString(R.string.menu_follow)) { begin(frozen = false) }
            else BubbleMenu.Item(getString(R.string.menu_frozen)) { begin(frozen = true) },
            BubbleMenu.Item(getString(R.string.menu_hide)) { onBubbleDropped() },
            BubbleMenu.Item(getString(R.string.menu_settings)) {
                startActivity(Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            },
        ))
    }

    private var select: SelectOverlay? = null

    /**
     * "Select text": freeze the screen, make its text selectable, copy or
     * translate the selection. Accessibility text is there at once; OCR adds
     * what only exists as pixels a moment later. Nothing leaves the phone
     * unless the user taps "Translate".
     */
    private fun startSelect() {
        dismiss(showBubble = false)
        bubble?.hide()
        val gen = generation
        main.postDelayed({
            if (gen != generation) return@postDelayed
            val screen = screenRect()
            val items = ScreenText.collect(this, screen)
            takeScreenshot { shot ->
                if (gen != generation) { shot?.recycle(); return@takeScreenshot }
                val overlay = SelectOverlay(this, wm, screen, shot, statusBarHeight(), navBarHeight(),
                    onCopy = { text -> copy(text); closeSelect() },
                    onTranslate = { text -> closeSelect(); openTranslate(text, "") },
                    onClose = ::closeSelect)
                select = overlay
                val a11y = items.mapIndexed { i, item -> SelectOverlay.linesOf(item, i) }
                overlay.setLines(a11y.flatten())
                overlay.attach()
                if (shot == null) {
                    if (items.isEmpty()) overlay.setHint(getString(R.string.select_none))
                    return@takeScreenshot
                }
                overlay.setHint(getString(R.string.select_reading))
                pool.execute {
                    val ocr = runCatching { Ocr.recognize(shot) }.getOrNull()
                    main.post {
                        if (select !== overlay) return@post
                        val lines = ocr?.lines.orEmpty()
                        // Web pages report text hidden under a sheet as visible: where
                        // the screenshot shows clearly different text, trust the pixels.
                        val keep = items.indices.filter { i -> !contradicted(items[i], lines) }
                        val kept = keep.map { items[it].bounds }
                        val top = statusBarHeight()
                        val extra = ocr?.raw.orEmpty().withIndex().filter { (_, b) ->
                            b.box.centerY() > top && kept.none { overlap(b.box, it) > 0.3 }
                        }.flatMap { (k, b) -> SelectOverlay.linesOf(b, items.size + k) }
                        overlay.setLines(keep.flatMap { a11y[it] } + extra)
                        overlay.setHint(getString(if (overlay.hasText) R.string.select_hint else R.string.select_none))
                    }
                }
            }
        }, 50)
    }

    /** OCR read something clearly different where this item claims to be. */
    private fun contradicted(item: ScreenItem, lines: List<Ocr.Line>): Boolean {
        val letters = item.text.filter { it.isLetter() }
        if (letters.length < 3) return false
        val seen = lines.filter { overlap(it.box, item.bounds) > 0.15 || overlap(item.bounds, it.box) > 0.15 }
        if (seen.isEmpty()) return false
        val ocr = seen.joinToString("") { it.text }
        return letters.count { it in ocr }.toDouble() / letters.length < 0.3
    }

    private fun closeSelect() {
        val s = select ?: return
        select = null
        s.detach()
        generation++
        if (session == null && ownUi == 0) bubble?.show()
    }

    private fun copy(text: String) {
        getSystemService(ClipboardManager::class.java)?.setPrimaryClip(ClipData.newPlainText("TransSnip", text))
        // Android 13+ shows its own "copied" note only for apps in front, not for this service.
        Toast.makeText(this, R.string.text_copied, Toast.LENGTH_SHORT).show()
    }

    private fun navBarHeight(): Int =
        resources.getIdentifier("navigation_bar_height", "dimen", "android")
            .takeIf { it != 0 }?.let { resources.getDimensionPixelSize(it) } ?: 0

    private fun statusBarHeight(): Int =
        resources.getIdentifier("status_bar_height", "dimen", "android")
            .takeIf { it != 0 }?.let { resources.getDimensionPixelSize(it) } ?: 0

    /** Off for real: the accessibility service disables itself (Android 7+). */
    fun turnOff() {
        closeSelect()
        dismiss(showBubble = false)
        menu.dismiss()
        Toast.makeText(this, R.string.turned_off, Toast.LENGTH_LONG).show()
        disableSelf()
    }

    private fun onOverlayTapEmpty() {
        if (lookup && startedLive) setLookup(false) else dismiss()
    }

    override fun onInterrupt() {}

    override fun onDestroy() {
        if (instance === this) instance = null
        main.post { stateListener?.invoke() }
        if (::settings.isInitialized) {
            select?.detach()
            select = null
            dismiss(showBubble = false)
            bubble?.remove()
            settings.offChange(prefListener)
        }
        pool.shutdownNow()
        super.onDestroy()
    }

    private fun syncBubble() {
        if (settings.bubble) {
            val b = bubble ?: Bubble(this, wm, settings, ::screenRect, ::onBubbleTap, ::onBubbleDropped, ::onBubbleLongPress)
                .also { bubble = it }
            if (session == null && select == null && ownUi == 0) b.show()
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
        if (menu.isShown) return menu.dismiss()
        if (live) dismiss() else begin(frozen = settings.frozenDefault)
    }

    private fun begin(frozen: Boolean) {
        lookup = frozen
        startedLive = !frozen
        start()
    }

    private fun onOwnUiChanged() {
        if (ownUi > 0) bubble?.hide() else if (session == null && select == null) bubble?.show()
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

    /** [quiet]: a live refresh — no "translating…" chip flashing on every scroll. */
    private fun capture(gen: Int, key: String, quiet: Boolean = false) {
        val started = SystemClock.uptimeMillis()
        live = true
        if (!quiet) livePkg = rootInActiveWindow?.packageName?.toString()
        val screen = screenRect()
        val target = settings.targetLang
        val exposed = ScreenText.collect(this, screen)
        val items = exposed.filter { Prompts.needsTranslation(it.text, target) }
        if (BuildConfig.DEBUG) exposed.forEach {
            android.util.Log.v("TransSnipItems", "${it.bounds.toShortString()} font=${it.fontPx} ${it.text.take(40).replace('\n', '|')}")
        }
        val overlay = ScreenOverlay(this, wm, screen, ::openBox, ::onOverlayTapEmpty, ::onSwipe)
        val s = Session(gen, overlay, started, quiet)
        session = s
        if (!quiet) overlay.setStatus(getString(R.string.screen_working))
        // Two waves: the exposed text goes out right now; OCR of the
        // screenshot then adds what only exists as pixels (video, images).
        s.waves = if (items.isNotEmpty()) 2 else 1
        if (items.isNotEmpty()) translate(s, key, s.add(items))
        takeScreenshot { shot ->
            if (gen != generation) return@takeScreenshot
            overlay.attach()
            overlay.setInteractive(lookup)
            s.frame = shot
            if (lookup) overlay.setFrozen(shot)
            bubble?.setActive(true, lookup)
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
                s.shotForCheck = shot
                val hidden = if (ocr != null) s.dropOccluded(ocr.lines) else emptySet()
                s.shotForCheck = null
                if (ocr != null) s.refineFrom(ocr.lines.map { it.box })
                val visible = exposed.filter { e -> e !in hidden }
                // The status bar (clock, icons) is in the screenshot too — never translate it.
                val statusBar = resources.getIdentifier("status_bar_height", "dimen", "android")
                    .takeIf { it != 0 }?.let { resources.getDimensionPixelSize(it) } ?: 0
                val extra = ocr?.blocks.orEmpty().filter { item ->
                    item.bounds.centerY() > statusBar &&
                        Prompts.needsTranslation(item.text, target) && visible.none { overlap(item.bounds, it) > 0.3 }
                }
                val range = s.add(extra)
                s.showBoxes(range)
                s.shot = null   // kept as s.frame (still-frame background), not recycled
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
        openTranslate(item.text, translation)
    }

    private fun openTranslate(text: String, translation: String) {
        startActivity(
            Intent(this, TranslateActivity::class.java)
                .setAction(Intent.ACTION_SEND)
                .setType("text/plain")
                .putExtra(Intent.EXTRA_TEXT, text)
                .putExtra(TranslateActivity.EXTRA_TRANSLATION, translation)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
        )
    }

    private fun dismiss(showBubble: Boolean = true) {
        generation++
        live = false
        lookup = false
        main.removeCallbacks(liveRecapture)
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

        /** TransSnip's main screen, to show the live state (service started / stopped). Main thread. */
        var stateListener: (() -> Unit)? = null

        fun ownUi(visible: Boolean) {
            ownUi = (ownUi + if (visible) 1 else -1).coerceAtLeast(0)
            instance?.onOwnUiChanged()
        }

        private const val SCROLL_START_MS = 450L   // no scroll event at all → content didn't move much
        private const val SCROLL_QUIET_MS = 250L
        private const val LIVE_QUIET_MS = 400L
        private const val PAD_OCR = 6
        private const val SLOW_MS = 3000L
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
    private inner class Session(val gen: Int, val overlay: ScreenOverlay, val started: Long, val quiet: Boolean = false) {
        val items = ArrayList<ScreenItem>()
        private val lines = ArrayList<List<String>>()
        private val translated = HashMap<String, String>()
        private val shown = HashSet<Int>()
        var shot: Bitmap? = null
        /** The screenshot these translations were made from (still-frame mode shows it). */
        var frame: Bitmap? = null
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

        /**
         * Web pages report text under an overlay (the page behind a comment
         * sheet) as visible, in an order that says nothing about what's on
         * top. The screenshot does: where OCR reads something clearly
         * different from an item's text, that item is covered — drop its box;
         * the OCR text there then gets translated instead.
         * Returns the dropped items' bounds.
         */
        /** The boxes share at least 15% of the smaller one's area. */
        private fun touches(a: Rect, b: Rect): Boolean {
            val r = Rect()
            if (!r.setIntersect(a, b)) return false
            val small = minOf(a.width().toLong() * a.height(), b.width().toLong() * b.height())
            return small > 0 && r.width().toLong() * r.height() * 100 >= small * 15
        }

        /** Screenshot kept until the OCR check is done (pixel test in [flat]). */
        var shotForCheck: Bitmap? = null

        /** Nearly one colour across the box: no glyphs there. */
        private fun flat(shot: Bitmap?, r: Rect): Boolean {
            if (shot == null || shot.isRecycled) return false
            val x0 = r.left.coerceIn(0, shot.width - 1); val x1 = r.right.coerceIn(x0 + 1, shot.width)
            val y0 = r.top.coerceIn(0, shot.height - 1); val y1 = r.bottom.coerceIn(y0 + 1, shot.height)
            var lo = 255; var hi = 0
            val stepX = maxOf(1, (x1 - x0) / 40); val stepY = maxOf(1, (y1 - y0) / 12)
            var y = y0
            while (y < y1) {
                var x = x0
                while (x < x1) {
                    val c = shot.getPixel(x, y)
                    val l = (android.graphics.Color.red(c) * 3 + android.graphics.Color.green(c) * 6 + android.graphics.Color.blue(c)) / 10
                    if (l < lo) lo = l
                    if (l > hi) hi = l
                    x += stepX
                }
                y += stepY
            }
            return hi - lo < 24
        }

        fun dropOccluded(ocrLines: List<Ocr.Line>): Set<Rect> {
            val dropped = HashSet<Rect>()
            for (i in shown.toList()) {
                val item = items[i]
                // An OCR line mostly inside the item, or the item mostly inside a
                // longer OCR line (a date next to "回复" reads as one line).
                // Any OCR line touching the item's area is evidence of what's
                // really drawn there.
                val seen = ocrLines.filter { touches(it.box, item.bounds) }
                val seenText = seen.joinToString("") { it.text }
                val letters = item.text.count { it.isLetter() }
                val keep = when {
                    // OCR read nothing there. Text always leaves contrast on
                    // screen; a flat patch means nothing is drawn at that spot.
                    seen.isEmpty() -> !flat(shotForCheck, item.bounds)
                    similarity(item.text, seenText) >= 0.3 -> true
                    // Very short labels ("回复") are where OCR misreads most
                    // ("凹是"): drop only against clearly different, longer text.
                    letters < 3 -> seenText.count { it.isLetter() } < 4
                    else -> false
                }
                if (BuildConfig.DEBUG) android.util.Log.v("TransSnipOcc", "${item.bounds.toShortString()} '${item.text.take(16).replace('\n', '|')}' " +
                    "seen=${seen.map { it.text.take(16) }} keep=$keep")
                if (keep) continue
                overlay.remove(i)
                shown -= i
                dropped += item.bounds
            }
            return dropped
        }

        /**
         * Share of [text]'s letters that also appear in [ocr] (OCR misreads a
         * few). Digits don't count — every date and timestamp shares them.
         */
        private fun similarity(text: String, ocr: String): Double {
            val chars = text.filter { it.isLetter() }
            if (chars.isEmpty()) return 1.0
            return chars.count { it in ocr }.toDouble() / chars.length
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

        private var firstAt = 0L
        private var doneMs = 0L

        fun deliver(line: String, translation: String) {
            if (firstAt == 0L) firstAt = SystemClock.uptimeMillis()
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
            // The time that matters is when the main text was done; OCR adding
            // a caption seconds later only updates the count, not the clock.
            val ms = doneMs.takeIf { it > 0 } ?: (SystemClock.uptimeMillis() - started)
            if (translated.isNotEmpty() && doneMs == 0L) doneMs = ms
            if (quiet && error == null) return   // live refresh: no chip unless something went wrong
            when {
                translated.isEmpty() && !last -> overlay.setStatus(getString(R.string.screen_ocr))
                items.isEmpty() -> overlay.setStatus(getString(R.string.screen_no_text), autoHideMs = 2500)
                translated.isEmpty() && error != null -> overlay.setStatus(getString(R.string.test_failed, error?.message))
                translated.isEmpty() -> overlay.setStatus(getString(R.string.screen_no_text), autoHideMs = 2500)
                hintShownThisRun -> overlay.setStatus(
                    getString(R.string.screen_done, shown.count { isTranslated(it) }, ms / 1000.0) + "\n" +
                        getString(if (lookup) R.string.frozen_hint else R.string.screen_hint), autoHideMs = 5000)
                else -> {
                    var done = getString(R.string.screen_done, shown.count { isTranslated(it) }, ms / 1000.0)
                    // Slow: was it the wait for the first answer, or the tail?
                    if (ms > SLOW_MS && firstAt > 0) done += getString(R.string.screen_slow, (firstAt - started) / 1000.0)
                    // The gestures aren't discoverable: spell them out the first few times.
                    if (settings.hintsShown < 3) {
                        settings.hintsShown += 1
                        hintShownThisRun = true
                        overlay.setStatus(done + "\n" + getString(if (lookup) R.string.frozen_hint else R.string.screen_hint), autoHideMs = 5000)
                    } else {
                        overlay.setStatus(done, autoHideMs = 1800)
                    }
                }
            }
        }
    }
}
