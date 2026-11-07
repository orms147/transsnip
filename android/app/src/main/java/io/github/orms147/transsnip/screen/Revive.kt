package io.github.orms147.transsnip.screen

import android.Manifest
import android.content.ComponentName
import android.content.Context
import android.content.pm.PackageManager
import android.os.Handler
import android.os.Looper
import android.provider.Settings

/**
 * Brings the screen service back without a trip to the accessibility
 * settings — possible only after a one-time
 * `adb shell pm grant io.github.orms147.transsnip android.permission.WRITE_SECURE_SETTINGS`.
 *
 * Why it's needed: Xiaomi (and others) kill the app's process when it is
 * swiped away from Recents. Android then marks the accessibility service as
 * "crashed" and never binds it again, although its switch still shows on.
 * Only taking it out of the enabled list and putting it back clears that.
 *
 * This touches nothing but TransSnip's own entry in that list.
 */
object Revive {

    fun allowed(context: Context) =
        context.checkSelfPermission(Manifest.permission.WRITE_SECURE_SETTINGS) == PackageManager.PERMISSION_GRANTED

    /** On in settings, but not running. */
    fun stalled(context: Context) = ScreenService.instance == null && enabledInSettings(context)

    fun enabledInSettings(context: Context) = enabledList(context).any { ComponentName.unflattenFromString(it) == me(context) }

    /**
     * Restart a stalled service (or, with [evenIfOff], switch it on). Returns
     * true if it was asked to start; it connects a moment later.
     */
    fun now(context: Context, evenIfOff: Boolean = false): Boolean {
        if (!allowed(context) || ScreenService.instance != null) return false
        val on = enabledInSettings(context)
        if (!on && !evenIfOff) return false   // turned off on purpose: leave it off
        val resolver = context.contentResolver
        val me = me(context)
        val others = enabledList(context).filter { ComponentName.unflattenFromString(it) != me }
        return runCatching {
            if (on) Settings.Secure.putString(resolver, Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES, others.joinToString(":"))
            // The system must see it gone before it comes back — two writes in a
            // row are read as one change, and "crashed" stays.
            Handler(Looper.getMainLooper()).postDelayed({
                runCatching {
                    Settings.Secure.putString(resolver, Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES,
                        (others + me.flattenToString()).joinToString(":"))
                    Settings.Secure.putInt(resolver, Settings.Secure.ACCESSIBILITY_ENABLED, 1)
                }
            }, if (on) GAP_MS else 0)
        }.isSuccess
    }

    private fun me(context: Context) = ComponentName(context, ScreenService::class.java)

    private fun enabledList(context: Context) =
        Settings.Secure.getString(context.contentResolver, Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES)
            .orEmpty().split(':').filter { it.isNotBlank() }

    private const val GAP_MS = 500L
}
