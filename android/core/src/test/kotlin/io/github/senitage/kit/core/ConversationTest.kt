package io.github.senitage.kit.core

import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import java.time.OffsetDateTime
import java.util.concurrent.CopyOnWriteArrayList
import kotlin.test.AfterTest
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/** A pretend Kit: keeps the messages, and answers each chat with "You said: ...". */
private class PretendKit : Dispatcher() {
    val messages = CopyOnWriteArrayList<String>()
    val chats = CopyOnWriteArrayList<String>()
    private var nextId = 1L

    fun add(role: String, text: String, channel: String = "phone"): Long {
        val id = nextId++
        messages += """{"id":$id,"at":"2026-10-12T08:00:00+11:00","role":"$role","text":"$text","channel":"$channel"}"""
        return id
    }

    override fun dispatch(request: RecordedRequest): MockResponse {
        val path = request.path ?: ""
        return when {
            path.startsWith("/api/messages") -> {
                val url = request.requestUrl!!
                val limit = url.queryParameter("limit")!!.toInt()
                val after = url.queryParameter("after")?.toLong()
                val before = url.queryParameter("before")?.toLong()
                val all = messages.mapIndexed { i, m -> (i + 1L) to m }
                val page = when {
                    after != null -> all.filter { it.first > after }.take(limit)
                    else -> all.filter { it.first < before!! }.takeLast(limit)
                }
                MockResponse().setBody(page.joinToString(",", "[", "]") { it.second })
            }
            path == "/api/chat" -> {
                val body = request.body.readUtf8()
                chats += body
                val text = Regex("\"text\":\"([^\"]*)\"").find(body)!!.groupValues[1]
                add("user", text)
                val id = add("assistant", "You said: $text")
                MockResponse().setBody(
                    listOf(
                        """{"type":"mood","emotion":"happy"}""",
                        """{"type":"say","text":"You said: "}""",
                        """{"type":"say","text":"$text"}""",
                        """{"type":"reply","reply":{"segments":[{"gesture":"nod","say":"You said: $text"}],"emotion":"happy"},"message_id":$id}""",
                    ).joinToString("\n"),
                )
            }
            path == "/api/chat/new" -> MockResponse().setBody("""{"ok":true}""")
            else -> MockResponse().setResponseCode(404)
        }
    }
}

class ConversationTest {
    private lateinit var server: MockWebServer
    private val kit = PretendKit()
    private var now = OffsetDateTime.parse("2026-10-12T08:00:00+11:00")
    private var ids = 0

    @BeforeTest
    fun start() {
        server = MockWebServer()
        server.dispatcher = kit
        server.start()
    }

    @AfterTest
    fun stop() {
        server.shutdown()
    }

    private fun conversation(scope: kotlinx.coroutines.CoroutineScope, store: Store = MemoryStore()) =
        Conversation(scope, store, clock = { now }, newId = { "id${ids++}" }).apply {
            client = KitClient(server.url("/").toString().trimEnd('/'), "t")
            body = "phone"
        }

    private fun texts(c: Conversation) = c.view.value.lines.map { "${it.who}: ${it.text}" }

    @Test
    fun `history loads, then a message and his answer`() = runBlocking<Unit> {
        kit.add("user", "morning", channel = "desk")
        kit.add("assistant", "Morning!", channel = "desk")
        val c = conversation(this)
        c.refresh()
        assertEquals(listOf("DAN: morning", "KIT: Morning!"), texts(c))
        assertEquals("desk", c.view.value.lines[0].channel)
        c.setOnline(true)
        c.send("hi from my phone")
        c.pump()?.join()
        assertEquals(listOf("DAN: morning", "KIT: Morning!", "DAN: hi from my phone", "KIT: You said: hi from my phone"), texts(c))
        assertTrue(c.view.value.lines.all { it.key.startsWith("m") }, "the live lines gave way to the saved ones")
        assertFalse(kit.chats.single().contains("sent_at"), "sent at once, so no time")
    }

    @Test
    fun `a message waits while kit's away and goes with the time it was written`() = runBlocking<Unit> {
        val store = MemoryStore()
        val c = conversation(this, store)
        c.setOnline(false)
        c.send("remind me about the bins")
        assertEquals(Sending.WAITING, c.view.value.lines.single().sending)
        assertEquals(1, c.waiting)
        assertTrue(store.read(Conversation.OUTBOX_FILE)!!.contains("bins"), "kept on the phone")

        // The app is closed and opened again later.
        now = now.plusMinutes(30)
        val again = conversation(this, store)
        again.load()
        assertEquals(Sending.WAITING, again.view.value.lines.single().sending)
        again.setOnline(true)
        again.pump()?.join()
        assertEquals(0, again.waiting)
        assertTrue(kit.chats.single().contains("\"sent_at\":\"2026-10-12T08:00:00+11:00\""), kit.chats.single())
        assertEquals(listOf("DAN: remind me about the bins", "KIT: You said: remind me about the bins"), texts(again))
    }

    @Test
    fun `kit out of reach keeps the message waiting`() = runBlocking<Unit> {
        val c = conversation(this)
        val troubles = mutableListOf<KitError>()
        c.trouble = { troubles += it }
        server.shutdown()
        c.setOnline(true)
        c.send("anyone there?")
        c.pump()?.join()
        assertEquals(1, c.waiting)
        assertEquals(Sending.WAITING, c.view.value.lines.single().sending)
        assertTrue(troubles.single() is KitError.Unreachable)
    }

    @Test
    fun `a pipe-up shows at once and the history catches up`() = runBlocking<Unit> {
        val c = conversation(this)
        c.refresh()
        val cues = mutableListOf<String>()
        c.cues = object : Cues {
            override fun reply(reply: Reply, pipeUp: Boolean) {
                cues += "reply pipeUp=$pipeUp"
            }
        }
        kit.add("assistant", "Still out?")
        c.pipeUp(Reply(listOf(Segment("Still out?", "wave"))))
        assertEquals(listOf("KIT: Still out?"), texts(c))
        assertEquals(listOf("reply pipeUp=true"), cues)
    }

    @Test
    fun `scrolling back loads older pages`() = runBlocking<Unit> {
        repeat(50) { kit.add("user", "m$it") }
        val c = conversation(this)
        c.refresh()
        assertEquals(Conversation.PAGE, c.view.value.lines.size)
        assertTrue(c.view.value.older)
        c.loadOlder()
        assertEquals(50, c.view.value.lines.size)
        assertEquals("m0", c.view.value.lines.first().text)
        assertFalse(c.view.value.older)
    }
}
