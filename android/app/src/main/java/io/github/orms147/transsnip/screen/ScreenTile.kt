package io.github.orms147.transsnip.screen

import android.annotation.SuppressLint
import android.app.PendingIntent
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.os.Build
import android.service.quicksettings.Tile
import android.service.quicksettings.TileService
import android.widget.Toast
import io.github.orms147.transsnip.AppSettings
import io.github.orms147.transsnip.MainActivity
import io.github.orms147.transsnip.R

/**
 * "TransSnip" in Quick Settings: an on/off switch for the bubble. Off keeps
 * the accessibility service enabled but idle, so turning it back on is one
 * tap — no trip to the accessibility settings. Until the service has been
 * enabled at all, the tile opens the setup screen.
 */
class ScreenTile : TileService() {

    override fun onStartListening() = update()

    private fun update() {
        val tile = qsTile ?: return
        val ready = ScreenService.instance != null
        val on = ready && AppSettings(this).bubble
        tile.state = if (on) Tile.STATE_ACTIVE else Tile.STATE_INACTIVE
        if (Build.VERSION.SDK_INT >= 29) {
            tile.subtitle = getString(when {
                !ready -> R.string.tile_setup
                on -> R.string.tile_on
                else -> R.string.tile_off
            })
        }
        tile.updateTile()
    }

    override fun onClick() {
        if (ScreenService.instance == null) return openSetup()
        val settings = AppSettings(this)
        settings.bubble = !settings.bubble
        Toast.makeText(this, if (settings.bubble) R.string.turned_on else R.string.bubble_hidden, Toast.LENGTH_SHORT).show()
        update()
    }

    @SuppressLint("StartActivityAndCollapseDeprecated")
    private fun openSetup() {
        val intent = Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        if (Build.VERSION.SDK_INT >= 34) {
            startActivityAndCollapse(PendingIntent.getActivity(this, 0, intent, PendingIntent.FLAG_IMMUTABLE))
        } else {
            @Suppress("DEPRECATION")
            startActivityAndCollapse(intent)
        }
    }

    companion object {
        /** Ask the system to redraw the tile (state changed elsewhere). */
        fun refresh(context: Context) {
            runCatching { requestListeningState(context, ComponentName(context, ScreenTile::class.java)) }
        }
    }
}
