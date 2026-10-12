package io.github.senitage.kit.core

import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.currentTime
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.io.File
import kotlin.random.Random
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class DirectorTest {
    private val kit2d = Character.parse(File("../../src/kit/face/characters/kit2d.json").readText())

    @Test
    fun `a reply is acted out, then he settles`() = runTest {
        val face = Face(kit2d, Random(2))
        val director = Director(this, face, { currentTime / 1000.0 }, Random(3))
        director.heard()
        assertEquals("thinking", face.state)
        director.reply(Reply(listOf(Segment("Morning!", "wave"), Segment("Coffee?", "tilt_head")), "happy"))
        advanceTimeBy(300)
        assertEquals("happy", face.emotion)
        assertEquals("speaking", face.state)
        assertEquals("Morning!", director.bubble.value)
        advanceTimeBy(10_000)
        assertEquals("idle", face.state)
        assertEquals("", director.bubble.value)
    }

    @Test
    fun `a show waits for his words`() = runTest {
        val face = Face(kit2d, Random(2))
        val director = Director(this, face, { currentTime / 1000.0 }, Random(3))
        val shown = mutableListOf<JsonObject>()
        director.onShow = { shown += it }
        director.heard()
        director.show(JsonObject(mapOf("kind" to JsonPrimitive("time"))))
        assertTrue(shown.isEmpty())
        director.reply(Reply(listOf(Segment("It's eight.", "none"))))
        advanceTimeBy(500)
        assertEquals(1, shown.size)
    }

    @Test
    fun `life events, being out of reach and a boop`() = runTest {
        val face = Face(kit2d, Random(2))
        val director = Director(this, face, { currentTime / 1000.0 }, Random(3))
        val buzzes = mutableListOf<String>()
        director.onBuzz = { buzzes += it }
        director.life(LifeEvent(1, "state", JsonObject(mapOf("state" to JsonPrimitive("asleep")))))
        assertEquals("sleeping", face.state)
        director.life(LifeEvent(2, "mood", JsonObject(mapOf("face" to JsonPrimitive("tired")))))
        assertEquals("tired", face.resting)
        director.setOnline(false)
        assertEquals("offline", face.state)
        director.boop()
        assertTrue(buzzes.isEmpty(), "no boops while he's out of reach")
        director.setOnline(true)
        assertEquals("sleeping", face.state)
        director.boop()
        assertEquals(listOf("boop"), buzzes)
        director.life(LifeEvent(3, "doing", JsonObject(mapOf("what" to JsonPrimitive("watching the rain")))))
        assertEquals("watching the rain...", director.bubble.value)
    }

    @Test
    fun `the 3D page hears only what changed`() {
        val face = Face(kit2d, Random(2))
        val mirror = Mirror(face)
        val first = mirror.calls()
        assertTrue("kit.setEmotion(\"neutral\");" in first)
        assertTrue("kit.setState(\"idle\");" in first)
        assertEquals(emptyList(), mirror.calls())
        face.play("nod", 1.0)
        face.setEmotion("happy", 1.0)
        assertEquals(listOf("kit.setEmotion(\"happy\");", "kit.play(\"nod\");"), mirror.calls())
        mirror.reset()
        assertTrue(mirror.calls().size >= 3)
    }
}
