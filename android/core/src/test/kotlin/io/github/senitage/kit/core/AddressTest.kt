package io.github.senitage.kit.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class AddressTest {
    @Test
    fun `an address is made whole`() {
        assertEquals("http://192.168.1.50:8600", KitAddress.normalize("192.168.1.50"))
        assertEquals("http://kit-server:8600", KitAddress.normalize(" kit-server "))
        assertEquals("http://kit-server:9000", KitAddress.normalize("kit-server:9000"))
        assertEquals("http://kit-server:8600", KitAddress.normalize("http://kit-server:8600/"))
        assertEquals("https://kit.example.ts.net", KitAddress.normalize("https://kit.example.ts.net"))
    }

    @Test
    fun `nonsense isn't an address`() {
        assertNull(KitAddress.normalize(""))
        assertNull(KitAddress.normalize("two words"))
        assertNull(KitAddress.normalize("ftp://kit-server"))
    }

    @Test
    fun `a pairing link from kit pair`() {
        val link = PairingLink.parse("kit://pair?url=http%3A%2F%2F192.168.1.50%3A8600&name=phone&token=abc%2B%2F%3D")
        assertEquals(PairingLink("http://192.168.1.50:8600", "phone", "abc+/="), link)
        assertNull(PairingLink.parse("https://example.com/?token=x"))
        assertNull(PairingLink.parse("kit://pair?url=192.168.1.50"))
    }

    @Test
    fun `device names kit accepts`() {
        assertEquals("my-pixel-8", DeviceName.tidy("My Pixel 8"))
        assertEquals("phone", DeviceName.tidy("!!!"))
        assertEquals(true, DeviceName.valid("phone-2"))
        assertEquals(false, DeviceName.valid("-phone"))
    }
}
