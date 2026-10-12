package io.github.senitage.kit.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class UpdatesTest {
    private val json = """[
      {"tag_name":"android-v0.1.12","name":"Kit for Android 0.1.12","prerelease":false,"draft":false,
       "assets":[{"name":"Kit-0.1.12.apk","browser_download_url":"https://example.com/12.apk","size":10}]},
      {"tag_name":"android-v0.1.15","name":"Test build","prerelease":true,"draft":false,
       "assets":[{"name":"Kit-0.1.15.apk","browser_download_url":"https://example.com/15.apk","size":10}]},
      {"tag_name":"desk-v0.1.200","name":"Desk","prerelease":false,"draft":false,
       "assets":[{"name":"Kit-Desk-Setup.exe","browser_download_url":"https://example.com/d.exe","size":10}]},
      {"tag_name":"android-v0.1.9","name":"old","prerelease":false,"draft":false,"assets":[]}
    ]"""

    @Test
    fun `the newest app release`() {
        val releases = Updates.parse(json)
        assertEquals(12, Updates.newest(releases, build = 10)?.build)
        assertEquals("https://example.com/12.apk", Updates.newest(releases, build = 10)?.apk?.url)
        assertNull(Updates.newest(releases, build = 12))
        assertEquals(15, Updates.newest(releases, build = 12, tests = true)?.build)
    }
}
