package io.github.senitage.kit.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

class NotifyTest {
    private fun message(id: Long, role: String, source: String?, text: String = "hello") =
        Message(id = id, role = role, text = text, source = source)

    @Test
    fun `a nudge carries only what it's about and the message to fetch`() {
        val nudge = Nudge.from(mapOf("kit" to "pipe_up", "id" to "42"))!!
        assertTrue(nudge.pipeUp)
        assertEquals(42L, nudge.messageId)
        assertEquals(Nudge("test", null), Nudge.from(mapOf("kit" to "test")))
        assertNull(Nudge.from(mapOf("id" to "42")))
        assertNull(Nudge.from(mapOf("kit" to " ")))
    }

    @Test
    fun `only his own pipe-ups since the last look become notifications`() {
        val messages = listOf(
            message(1, "assistant", "pipe_up", "old"),
            message(2, "user", null, "Dan"),
            message(3, "assistant", "chat", "an answer"),
            message(5, "assistant", "pipe_up", "later one"),
            message(4, "assistant", "pipe_up", "earlier one"),
            message(6, "assistant", "pipe_up", "   "),
        )
        assertEquals(listOf(4L, 5L), newPipeUps(messages, after = 1).map { it.id })
        assertEquals(listOf(5L), newPipeUps(messages, after = 1, most = 1).map { it.id })
        assertEquals(emptyList(), newPipeUps(messages, after = 6))
    }

    @Test
    fun `the phone remembers the newest message it saw`() {
        val messages = listOf(message(3, "user", null), message(9, "assistant", "pipe_up"))
        assertEquals(9L, seenUpTo(messages, before = 4))
        assertEquals(12L, seenUpTo(messages, before = 12))
        assertEquals(2L, seenUpTo(emptyList(), before = 2))
    }
}
