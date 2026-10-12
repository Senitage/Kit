package io.github.senitage.kit.core

import kotlinx.coroutines.flow.toList
import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.SocketPolicy
import java.time.OffsetDateTime
import kotlin.test.AfterTest
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertIs
import kotlin.test.assertNull
import kotlin.test.assertTrue

class KitClientTest {
    private lateinit var server: MockWebServer
    private lateinit var client: KitClient

    @BeforeTest
    fun start() {
        server = MockWebServer()
        server.start()
        client = KitClient(server.url("/").toString().trimEnd('/'), "phone-token")
    }

    @AfterTest
    fun stop() {
        server.shutdown()
    }

    @Test
    fun `health needs no token`() = runBlocking<Unit> {
        server.enqueue(MockResponse().setBody("""{"ok":true,"name":"Kit","version":"0.1.0"}"""))
        assertEquals(Health(true, "Kit", "0.1.0"), client.health())
        assertNull(server.takeRequest().getHeader("Authorization"))
    }

    @Test
    fun `pairing swaps kit's token for the phone's own`() = runBlocking<Unit> {
        server.enqueue(MockResponse().setBody("""{"name":"phone","kind":"phone","token":"new"}"""))
        assertEquals("new", client.pair("phone").token)
        val request = server.takeRequest()
        assertEquals("/api/devices/pair", request.path)
        assertEquals("Bearer phone-token", request.getHeader("Authorization"))
        assertEquals("""{"name":"phone","kind":"phone"}""", request.body.readUtf8())
    }

    @Test
    fun `a refused token and a phone that may not pair`() = runBlocking<Unit> {
        server.enqueue(MockResponse().setResponseCode(401).setBody("""{"detail":"missing or wrong token"}"""))
        assertFailsWith<KitError.BadToken> { client.life() }
        server.enqueue(MockResponse().setResponseCode(403).setBody("""{"detail":"only Kit's own token can pair"}"""))
        val e = assertFailsWith<KitError.NotAllowed> { client.pair("phone") }
        assertEquals("only Kit's own token can pair", e.message)
    }

    @Test
    fun `hello says what the phone can do`() = runBlocking<Unit> {
        server.enqueue(
            MockResponse().setBody(
                """{"api":1,"kit":"0.1.0","name":"Kit","features":{"chat":2,"messages":2,"brand_new":1},
                   "events":["mood"],"face":{"character":"kit3d","style":"model","page":"/face/?app=phone"},
                   "unknown_abilities":[],"something_else":{"x":1}}""",
            ),
        )
        val answer = client.hello(Hello(app = "0.1.3"))
        assertTrue(answer.has("chat", 2))
        assertTrue(!answer.has("voice_out"))
        assertEquals("model", answer.face.style)
        assertEquals(server.url("/face/?app=phone").toString(), client.facePage(answer.face.page))
        val sent = server.takeRequest().body.readUtf8()
        assertTrue(sent.contains("\"kind\":\"phone\"") && sent.contains("\"screen\""), sent)
    }

    @Test
    fun `history pages`() = runBlocking<Unit> {
        server.enqueue(MockResponse().setBody("""[{"id":5,"at":"2026-10-12T08:00:00+11:00","role":"user","text":"hi","channel":"desk"}]"""))
        val page = client.messages(40)
        assertEquals("/api/messages?limit=40&before=${Long.MAX_VALUE}", server.takeRequest().path)
        assertEquals("desk", page.single().channel)
        server.enqueue(MockResponse().setBody("[]"))
        client.messages(100, after = 5)
        assertEquals("/api/messages?limit=100&after=5", server.takeRequest().path)
    }

    @Test
    fun `a chat streams its events`() = runBlocking<Unit> {
        val lines = listOf(
            """{"type":"mood","emotion":"curious"}""",
            """{"type":"say","text":"Hello"}""",
            """{"type":"spoken"}""",
            """{"type":"reply","reply":{"segments":[{"gesture":"wave","say":"Hello"}],"emotion":"happy"},"message_id":9}""",
        )
        server.enqueue(MockResponse().setBody(lines.joinToString("\n") + "\n"))
        val written = OffsetDateTime.parse("2026-10-12T07:40:00+11:00")
        val events = client.chat("hi", body = "phone", sentAt = written).toList()
        assertEquals(ChatEvent.Accepted, events[0])
        assertEquals(ChatEvent.Mood("curious"), events[1])
        assertIs<ChatEvent.Done>(events.last())
        val sent = server.takeRequest().body.readUtf8()
        assertEquals("""{"text":"hi","channel":"phone","body":"phone","sent_at":"2026-10-12T07:40:00+11:00"}""", sent)
    }

    @Test
    fun `nobody there is unreachable`() = runBlocking<Unit> {
        server.enqueue(MockResponse().setSocketPolicy(SocketPolicy.DISCONNECT_AT_START))
        assertFailsWith<KitError.Unreachable> { client.chat("hi").toList() }
        server.shutdown()
        assertFailsWith<KitError.Unreachable> { client.health() }
    }

    @Test
    fun `the phone tells kit how to nudge it and where dan is`() = runBlocking<Unit> {
        server.enqueue(MockResponse().setBody("""{"ok":true,"nudges":true}"""))
        assertTrue(client.registerPush("phone", "fcm", "tok-1"))
        val sent = server.takeRequest()
        assertEquals("/api/devices/phone/push", sent.path)
        assertEquals("""{"kind":"fcm","token":"tok-1"}""", sent.body.readUtf8())
        server.enqueue(MockResponse().setBody("""{"ok":true,"nudges":false}"""))
        assertTrue(!client.registerPush("phone", "fcm", "tok-1"))
        server.takeRequest()
        server.enqueue(MockResponse().setBody("""{"ok":true}"""))
        client.unregisterPush("phone")
        assertEquals("DELETE", server.takeRequest().method)

        server.enqueue(MockResponse().setBody("""{"ok":true,"line":"Dan's phone says they're out."}"""))
        val line = client.report(PhoneReport("out", "2026-10-12T09:00:00+11:00", 55, false))
        assertEquals("Dan's phone says they're out.", line)
        val report = server.takeRequest()
        assertEquals("/api/phone/context", report.path)
        assertEquals("""{"place":"out","since":"2026-10-12T09:00:00+11:00","battery":55,"charging":false}""", report.body.readUtf8())
    }

    @Test
    fun `his notebook, memory and settings come through`() = runBlocking<Unit> {
        server.enqueue(MockResponse().setBody("""{"sheet":{"id":1,"source":"self","kind":"sheet","text":"I am Kit"},"quirks":["hums"],"wants":[],"unknown":1}"""))
        val notebook = client.notebook()
        assertEquals("I am Kit", notebook.sheet?.text)
        assertEquals(listOf("hums"), notebook.quirks)
        assertEquals("/api/life/notebook", server.takeRequest().path)

        server.enqueue(MockResponse().setBody("""{"mood":"calm","face":"neutral","snoozed_until":"2026-10-12T10:00","last_event":3}"""))
        assertEquals("2026-10-12T10:00", client.snooze(60).snoozedUntil)
        assertEquals("""{"minutes": 60}""", server.takeRequest().body.readUtf8())

        server.enqueue(MockResponse().setBody("""{"decision":"learned","id":7,"replaced":null}"""))
        assertEquals(Learned("learned", 7, null), client.teach("Dan likes tea", "likes"))
        assertEquals("""{"text":"Dan likes tea","kind":"likes","pinned":false}""", server.takeRequest().body.readUtf8())

        server.enqueue(MockResponse().setBody("""{"id":7,"source":"facts","kind":"likes","text":"Dan likes tea","pinned":true}"""))
        assertTrue(client.pinFact(7, true).pinned)
        val pin = server.takeRequest()
        assertEquals("PATCH", pin.method)
        assertEquals("/api/memory/facts/7", pin.path)

        server.enqueue(MockResponse().setBody("""{"words_only":true,"hits":[{"id":7,"source":"facts","text":"Dan likes tea","similarity":0.8,"word_match":true}]}"""))
        val found = client.search("tea", most = 5)
        assertTrue(found.wordsOnly)
        assertEquals(0.8, found.hits.single().similarity)
        assertEquals("/api/memory/search?q=tea&k=5", server.takeRequest().path)

        server.enqueue(MockResponse().setBody("""[{"id":2,"name":"Richmond","kind":"place","links":[{"system":"notes","target":"Places/Richmond.md"}],"line":"Richmond (place)"}]"""))
        assertEquals("notes", client.things().single().links.single().system)
        server.takeRequest()

        server.enqueue(MockResponse().setBody("""{"settings":{"phone":{"notify":"away"}},"problem":null}"""))
        assertEquals("away", SettingsForm.text(SettingsForm.value(client.settings().settings, "phone", "notify")))
        server.takeRequest()
        server.enqueue(MockResponse().setBody("""{"settings":{"phone":{"notify":"never"}}}"""))
        client.changeSettings(SettingsForm.patch("phone", "notify", kotlinx.serialization.json.JsonPrimitive("never")))
        val change = server.takeRequest()
        assertEquals("PATCH", change.method)
        assertEquals("phone", change.getHeader("X-Changed-By"))
        assertEquals("""{"phone":{"notify":"never"}}""", change.body.readUtf8())

        server.enqueue(MockResponse().setBody("""{"month_usd":3.25,"cap_usd":40,"days":[]}"""))
        assertEquals(Spend(3.25, 40.0), client.spend())
        assertEquals("/api/spend/summary?days=30", server.takeRequest().path)
    }
}
