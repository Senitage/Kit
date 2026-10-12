package io.github.senitage.kit.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertNull

class EventsTest {
    @Test
    fun `the chat events kit sends`() {
        assertEquals(ChatEvent.Mood("happy"), ChatEvent.parse("""{"type":"mood","emotion":"happy"}"""))
        assertEquals(ChatEvent.Say("Hi", cloud = true), ChatEvent.parse("""{"type":"say","text":"Hi","source":"cloud"}"""))
        assertEquals(ChatEvent.Doing("remembering"), ChatEvent.parse("""{"type":"recalled","query":"x"}"""))
        assertEquals(ChatEvent.HandingOff("Sonnet"), ChatEvent.parse("""{"type":"handing_off","to":"Sonnet","question":"q"}"""))
        assertEquals(ChatEvent.Note("Updated memory: the car is blue"), ChatEvent.parse("""{"type":"remembered","decision":"update","fact":"the car is blue"}"""))
        assertEquals(ChatEvent.Error("Oops"), ChatEvent.parse("""{"type":"error","message":"Oops"}"""))
        val done = ChatEvent.parse(
            """{"type":"reply","source":"local","message_id":12,"role":"chat","reply":{"segments":[{"gesture":"nod","say":"Sure."},{"gesture":"none","say":"Done."}],"emotion":"happy","action":{"kind":"none"},"detail":"- a"}}""",
        )
        assertIs<ChatEvent.Done>(done)
        assertEquals("Sure. Done.", done.reply.text)
        assertEquals("happy", done.reply.emotion)
        assertEquals("- a", done.reply.detail)
        assertEquals(12L, done.messageId)
    }

    @Test
    fun `unknown and broken lines are skipped`() {
        assertEquals(ChatEvent.Other("sound"), ChatEvent.parse("""{"type":"sound","sound":"chuckle"}"""))
        assertEquals(ChatEvent.Other("something_new"), ChatEvent.parse("""{"type":"something_new","x":1}"""))
        assertNull(ChatEvent.parse("not json"))
        assertNull(ChatEvent.parse("   "))
    }

    @Test
    fun `a pipe-up life event carries its reply`() {
        val raw = KitJson.parseToJsonElement(
            """{"id":7,"type":"pipe_up","reply":{"segments":[{"gesture":"wave","say":"Still out?"}],"emotion":"playful"},"to":"desk:pc","aloud":true}""",
        )
        val event = LifeEvent.from(raw as kotlinx.serialization.json.JsonObject)
        assertEquals(7L, event.id)
        assertEquals("pipe_up", event.type)
        assertEquals("Still out?", event.reply?.text)
        assertEquals("desk:pc", event.str("to"))
    }
}
