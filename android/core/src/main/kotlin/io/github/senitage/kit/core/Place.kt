package io.github.senitage.kit.core

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * Where the phone says Dan is, worked out on the phone (kit.phone_context): home
 * while it's on the Wi-Fi he marked as home, out on mobile data or another
 * network, unknown otherwise. Kit only ever gets the word, never a place.
 */
enum class Place(val word: String) {
    HOME("home"),
    OUT("out"),
    UNKNOWN("unknown"),
}

/**
 * What the phone can see of the network it's on, with nothing in it that names a
 * place: whether it's Wi-Fi or mobile data, and a fingerprint of the Wi-Fi network
 * (its gateway and DNS addresses, hashed) to recognise home by.
 */
data class NetworkSeen(val wifi: Boolean, val cellular: Boolean, val fingerprint: String?) {
    companion object {
        val NONE = NetworkSeen(wifi = false, cellular = false, fingerprint = null)

        /** A fingerprint from the Wi-Fi network's addresses (any order), or null if none. */
        fun fingerprint(parts: Collection<String>): String? {
            val clean = parts.map { it.trim() }.filter { it.isNotEmpty() }.sorted()
            if (clean.isEmpty()) return null
            return clean.joinToString("|").hashCode().toUInt().toString(16)
        }
    }
}

/** Home or out, from what the phone sees and the Wi-Fi marked as home. */
fun decidePlace(seen: NetworkSeen, home: String?): Place = when {
    seen.wifi && home != null && seen.fingerprint == home -> Place.HOME
    seen.wifi && home != null && seen.fingerprint != null -> Place.OUT
    seen.cellular && !seen.wifi -> Place.OUT
    else -> Place.UNKNOWN
}

/** One report to Kit (`POST /api/phone/context`). */
@Serializable
data class PhoneReport(
    val place: String = Place.UNKNOWN.word,
    val since: String? = null,
    val battery: Int? = null,
    val charging: Boolean? = null,
)

/**
 * Keeps the phone's place and decides when Kit should hear about it: when the
 * place changes, when the battery crosses low or starts charging, and at most
 * every [everyS] seconds otherwise (so a nearly flat battery stays fresh).
 */
class PlaceTracker(
    var home: String? = null,
    private val now: () -> String,
    private val everyS: Long = 30 * 60,
) {
    var place: Place = Place.UNKNOWN
        private set
    var since: String? = null
        private set
    private var lastSent: PhoneReport? = null
    private var lastSentAt: Long = Long.MIN_VALUE

    /** Mark the Wi-Fi the phone is on as home (or forget home with null). */
    fun markHome(fingerprint: String?) {
        home = fingerprint
    }

    /** What the phone sees now; returns the report to send, or null if nothing's new. */
    fun look(seen: NetworkSeen, battery: Int?, charging: Boolean?, atS: Long): PhoneReport? {
        val decided = decidePlace(seen, home)
        if (decided != place) {
            place = decided
            since = now()
        }
        val report = PhoneReport(place.word, since, battery, charging)
        val last = lastSent
        val due = last == null ||
            last.place != report.place ||
            (last.charging != report.charging) ||
            crossedLow(last.battery, report.battery) ||
            atS - lastSentAt >= everyS
        if (!due) return null
        lastSent = report
        lastSentAt = atS
        return report
    }

    /** The last report sent (to send again on purpose), or what it would be now. */
    fun last(): PhoneReport = lastSent ?: PhoneReport(place.word, since, null, null)

    private fun crossedLow(before: Int?, after: Int?): Boolean {
        if (before == null || after == null) return before != after
        return (before < LOW) != (after < LOW)
    }

    companion object {
        /** The battery level Kit mentions below (kit.phone_context.FLAT_BELOW). */
        const val LOW = 20
    }
}

/** The phone's own switches for what it tells Kit, kept on the phone. */
@Serializable
data class Senses(
    @SerialName("tell_place") val tellPlace: Boolean = true,
    @SerialName("tell_battery") val tellBattery: Boolean = true,
    val notify: Boolean = true,
)
