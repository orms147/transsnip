package io.github.orms147.transsnip.screen

import android.annotation.SuppressLint
import android.app.PendingIntent
import android.content.Intent
import android.os.Build
import android.service.quicksettings.Tile
import android.service.quicksettings.TileService
import io.github.orms147.transsnip.MainActivity

/**
 * "Dịch màn hình" in Quick Settings — screen translation without the bubble.
 * Until the accessibility service is on, the tile opens the setup screen.
 */
class ScreenTile : TileService() {

    override fun onStartListening() {
        qsTile?.apply {
            // Not UNAVAILABLE when the service is off: that would swallow the
            // click that opens the setup screen.
            state = Tile.STATE_INACTIVE
            if (Build.VERSION.SDK_INT >= 29) {
                subtitle = if (ScreenService.instance != null) null
                else getString(io.github.orms147.transsnip.R.string.tile_setup)
            }
            updateTile()
        }
    }

    override fun onClick() {
        val service = ScreenService.instance
        if (service != null) {
            service.translateFromTile()
        } else {
            openSetup()
        }
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
}
