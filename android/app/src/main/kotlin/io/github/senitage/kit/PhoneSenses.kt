package io.github.senitage.kit

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.SharedPreferences
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.os.BatteryManager
import io.github.senitage.kit.core.KitClient
import io.github.senitage.kit.core.NetworkSeen
import io.github.senitage.kit.core.Place
import io.github.senitage.kit.core.PlaceTracker
import io.github.senitage.kit.core.Senses
import io.github.senitage.kit.core.decidePlace
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import java.time.OffsetDateTime
import java.time.format.DateTimeFormatter

/**
 * What the phone tells Kit about itself (kit.phone_context): whether Dan's home or
 * out, worked out from the Wi-Fi he marked as home (never a location), and the
 * battery. Each sense has a switch on the Settings page, kept on the phone.
 */
class PhoneSenses(
    private val context: Context,
    private val prefs: SharedPreferences,
    private val client: () -> KitClient?,
) {
    private val tracker = PlaceTracker(
        home = prefs.getString(HOME, null),
        now = { OffsetDateTime.now().format(DateTimeFormatter.ISO_OFFSET_DATE_TIME) },
    )

    private val _senses = MutableStateFlow(
        Senses(
            tellPlace = prefs.getBoolean(TELL_PLACE, true),
            tellBattery = prefs.getBoolean(TELL_BATTERY, true),
            notify = prefs.getBoolean(NOTIFY, true),
        ),
    )
    val senses: StateFlow<Senses> = _senses.asStateFlow()

    private val _line = MutableStateFlow(prefs.getString(LINE, "") ?: "")

    /** The line Kit sees, as he last confirmed it. */
    val line: StateFlow<String> = _line.asStateFlow()

    val homeMarked: Boolean get() = tracker.home != null

    /** Whether the phone is on the Wi-Fi marked as home right now. */
    val atHome: Boolean get() = decidePlace(seen(), tracker.home) == Place.HOME

    val onWifi: Boolean get() = seen().wifi

    fun set(senses: Senses) {
        _senses.value = senses
        prefs.edit()
            .putBoolean(TELL_PLACE, senses.tellPlace)
            .putBoolean(TELL_BATTERY, senses.tellBattery)
            .putBoolean(NOTIFY, senses.notify)
            .apply()
    }

    /** Mark the Wi-Fi the phone is on as home. False when it isn't on Wi-Fi. */
    fun markHomeHere(): Boolean {
        val fingerprint = seen().takeIf { it.wifi }?.fingerprint ?: return false
        tracker.markHome(fingerprint)
        prefs.edit().putString(HOME, fingerprint).apply()
        return true
    }

    fun forgetHome() {
        tracker.markHome(null)
        prefs.edit().remove(HOME).apply()
    }

    /**
     * The network as the phone sees it: Wi-Fi or mobile data, and a fingerprint of
     * the Wi-Fi's gateway and DNS addresses. Needs no location permission.
     */
    fun seen(): NetworkSeen {
        val cm = context.getSystemService(ConnectivityManager::class.java) ?: return NetworkSeen.NONE
        val network = cm.activeNetwork ?: return NetworkSeen.NONE
        val caps = cm.getNetworkCapabilities(network) ?: return NetworkSeen.NONE
        val wifi = caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) || caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET)
        val cellular = caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR)
        // Over a VPN (Tailscale) the real network is underneath; its link is what's fingerprinted.
        val link = cm.getLinkProperties(network)
        val parts = mutableListOf<String>()
        link?.routes?.filter { it.isDefaultRoute }?.forEach { route -> route.gateway?.hostAddress?.let { parts += it } }
        link?.dnsServers?.forEach { it.hostAddress?.let { address -> parts += address } }
        return NetworkSeen(wifi, cellular && !wifi, if (wifi) NetworkSeen.fingerprint(parts) else null)
    }

    /** The battery, 0-100, and whether it's charging. */
    fun battery(): Pair<Int?, Boolean?> {
        val bm = context.getSystemService(BatteryManager::class.java) ?: return null to null
        val level = bm.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY).takeIf { it in 0..100 }
        return level to bm.isCharging
    }

    /**
     * Tell Kit how the phone is, when something's changed (or [force]). True when
     * there was nothing to send or Kit took it.
     */
    suspend fun report(force: Boolean = false): Boolean {
        val c = client() ?: return true
        val s = _senses.value
        val seen = if (s.tellPlace) seen() else NetworkSeen.NONE
        val (level, charging) = if (s.tellBattery) battery() else (null to null)
        val nowS = System.currentTimeMillis() / 1000
        val report = tracker.look(seen, level, charging, nowS) ?: if (force) tracker.last() else null
        if (report == null) return true
        return try {
            val line = c.report(report)
            _line.value = line
            prefs.edit().putString(LINE, line).apply()
            true
        } catch (e: Exception) {
            false
        }
    }

    companion object {
        private const val HOME = "home_wifi"
        private const val TELL_PLACE = "tell_place"
        private const val TELL_BATTERY = "tell_battery"
        private const val NOTIFY = "notify"
        private const val LINE = "phone_line"
    }
}

/** The battery going low or okay and the charger coming or going: tell Kit. */
class SensesReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        when (intent.action) {
            Intent.ACTION_BATTERY_LOW, Intent.ACTION_BATTERY_OKAY,
            Intent.ACTION_POWER_CONNECTED, Intent.ACTION_POWER_DISCONNECTED,
            -> CatchUpWorker.now(context)
        }
    }
}
