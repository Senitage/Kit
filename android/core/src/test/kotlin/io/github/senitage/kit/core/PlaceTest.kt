package io.github.senitage.kit.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull

class PlaceTest {
    private val home = NetworkSeen.fingerprint(listOf("192.168.1.1", "192.168.1.1"))!!
    private val onHome = NetworkSeen(wifi = true, cellular = false, fingerprint = home)
    private val onOtherWifi = NetworkSeen(wifi = true, cellular = false, fingerprint = "abc123")
    private val onData = NetworkSeen(wifi = false, cellular = true, fingerprint = null)

    @Test
    fun `a fingerprint is the same whatever the order and empty when there's nothing`() {
        assertEquals(home, NetworkSeen.fingerprint(listOf(" 192.168.1.1", "192.168.1.1 ")))
        assertEquals(
            NetworkSeen.fingerprint(listOf("b", "a")),
            NetworkSeen.fingerprint(listOf("a", "b")),
        )
        assertNull(NetworkSeen.fingerprint(listOf("", "  ")))
        // It never holds the address itself.
        assert(!home.contains("192"))
    }

    @Test
    fun `home is the marked wifi and out is data or someone else's wifi`() {
        assertEquals(Place.HOME, decidePlace(onHome, home))
        assertEquals(Place.OUT, decidePlace(onOtherWifi, home))
        assertEquals(Place.OUT, decidePlace(onData, home))
        assertEquals(Place.OUT, decidePlace(onData, null))
        assertEquals(Place.UNKNOWN, decidePlace(onOtherWifi, null))
        assertEquals(Place.UNKNOWN, decidePlace(NetworkSeen.NONE, home))
        assertEquals(Place.UNKNOWN, decidePlace(NetworkSeen(true, false, null), home))
    }

    @Test
    fun `the tracker reports a change of place, of charging, a flat battery and now and then`() {
        var clock = "2026-10-12T08:00:00+11:00"
        val tracker = PlaceTracker(home = home, now = { clock }, everyS = 600)
        val first = tracker.look(onHome, 80, false, atS = 0)
        assertEquals(PhoneReport("home", clock, 80, false), first)
        assertNull(tracker.look(onHome, 79, false, atS = 10))
        clock = "2026-10-12T08:30:00+11:00"
        assertEquals(PhoneReport("out", clock, 75, false), tracker.look(onData, 75, false, atS = 100))
        assertEquals(clock, tracker.since)
        assertEquals("out", tracker.look(onData, 70, true, atS = 110)?.place)
        assertNull(tracker.look(onData, 60, true, atS = 120))
        assertEquals(19, tracker.look(onData, 19, true, atS = 130)?.battery)
        assertNull(tracker.look(onData, 18, true, atS = 140))
        assertNotNull(tracker.look(onData, 17, true, atS = 740))
        // Going home again is a new "since".
        clock = "2026-10-12T18:00:00+11:00"
        assertEquals(PhoneReport("home", clock, 17, true), tracker.look(onHome, 17, true, atS = 800))
    }

    @Test
    fun `marking home changes what the same wifi means`() {
        val tracker = PlaceTracker(now = { "t" })
        assertEquals("unknown", tracker.look(onOtherWifi, null, null, atS = 0)?.place)
        tracker.markHome(onOtherWifi.fingerprint)
        assertEquals("home", tracker.look(onOtherWifi, null, null, atS = 1)?.place)
        tracker.markHome(null)
        assertEquals("unknown", tracker.look(onOtherWifi, null, null, atS = 2)?.place)
    }

    @Test
    fun `the report and senses go as json kit reads`() {
        assertEquals(
            """{"place":"out","since":"t","battery":12,"charging":false}""",
            KitJson.encodeToString(PhoneReport.serializer(), PhoneReport("out", "t", 12, false)),
        )
        assertEquals("""{"place":"unknown"}""", KitJson.encodeToString(PhoneReport.serializer(), PhoneReport()))
        assertEquals(
            Senses(tellPlace = false, tellBattery = true, notify = true),
            KitJson.decodeFromString(Senses.serializer(), """{"tell_place":false}"""),
        )
    }
}
