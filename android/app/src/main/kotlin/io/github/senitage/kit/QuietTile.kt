package io.github.senitage.kit

import android.os.Build
import android.service.quicksettings.Tile
import android.service.quicksettings.TileService
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter

/** A Quick Settings tile: hush Kit for an hour, or let him speak again. */
class QuietTile : TileService() {
    private val kit: Kit get() = (application as KitApp).kit

    override fun onStartListening() {
        draw()
    }

    override fun onClick() {
        val quiet = kit.quietUntil.value != null
        ActWorker.quiet(this, if (quiet) 0 else 60)
        qsTile?.apply {
            state = Tile.STATE_UNAVAILABLE
            updateTile()
        }
    }

    private fun draw() {
        val tile = qsTile ?: return
        val until = kit.quietUntil.value
        tile.state = when {
            !kit.paired.value -> Tile.STATE_UNAVAILABLE
            until != null -> Tile.STATE_ACTIVE
            else -> Tile.STATE_INACTIVE
        }
        tile.label = if (until != null) "${kit.name} is quiet" else "Hush ${kit.name}"
        if (Build.VERSION.SDK_INT >= 29) {
            tile.subtitle = when {
                until != null -> "until ${clock(until)}"
                kit.paired.value -> "for an hour"
                else -> "not paired"
            }
        }
        tile.updateTile()
    }

    private fun clock(at: String): String =
        runCatching { LocalDateTime.parse(at.take(16)).format(DateTimeFormatter.ofPattern("h:mm a")) }.getOrDefault(at)
}
