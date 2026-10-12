package io.github.senitage.kit.core

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.jsonObject
import java.io.File
import kotlin.math.abs
import kotlin.random.Random
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertTrue
import kotlin.test.fail

/** The port of kit.face.character against numbers made by the Python (tests/test_android.py). */
class CharacterTest {
    private val sheets = File("../../src/kit/face/characters")
    private val reference = KitJson.parseToJsonElement(
        javaClass.getResource("/face_reference.json")!!.readText(),
    ).jsonObject

    private fun character(name: String) = Character.parse(File(sheets, "$name.json").readText())

    private fun same(expected: JsonObject, got: Map<String, Double>, what: String) {
        for ((key, value) in expected) {
            val want = (value as JsonPrimitive).doubleOrNull ?: continue
            val have = got[key] ?: fail("$what: no $key")
            if (abs(want - have) > 1e-9) fail("$what $key: want $want, got $have")
        }
    }

    @Test
    fun `poses, gestures and states match the brain's`() {
        for ((name, ref) in reference) {
            val c = character(name)
            val r = ref.jsonObject
            for ((emotion, pose) in r["poses"]!!.jsonObject) same(pose.jsonObject, c.pose(emotion), "$name pose $emotion")
            for ((gesture, moves) in r["gestures"]!!.jsonObject) {
                val m = moves.jsonObject
                assertEquals((m["seconds"] as JsonPrimitive).doubleOrNull, c.gestureSeconds(gesture), "$name $gesture seconds")
                for (t in listOf("0.1", "0.37", "0.8")) {
                    same(m[t]!!.jsonObject, c.gestureAt(gesture, t.toDouble()), "$name $gesture at $t")
                }
            }
            for ((state, byEmotion) in r["states"]!!.jsonObject) {
                for ((emotion, pose) in byEmotion.jsonObject) {
                    same(pose.jsonObject, c.statePose(state, emotion, c.pose(emotion)), "$name $state $emotion")
                }
            }
            for ((state, glow) in r["glow"]!!.jsonObject) {
                assertEquals((glow as JsonPrimitive).doubleOrNull, c.stateGlow(state), "$name glow $state")
            }
            for ((emotion, colour) in r["colours"]!!.jsonObject) {
                val want = (colour as? JsonPrimitive)?.takeIf { it.isString }?.content
                assertEquals(want, c.moodColour(emotion), "$name colour $emotion")
            }
        }
    }

    @Test
    fun `the phone draws a 3D character's 2D fallback`() {
        val kit3d = character("kit3d")
        assertEquals("model", kit3d.look(styles = setOf("glow", "model"))?.str("style"))
        assertEquals("glow", kit3d.look(styles = setOf("glow"))?.str("style"))
        assertNotNull(character("kit2d").look()?.obj("mouth"))
    }

    @Test
    fun `the face moves, blinks and settles`() {
        val face = Face(character("kit2d"), Random(1))
        var t = 0.0
        var frame = face.tick(t)
        face.setEmotion("happy", t, holdS = 1.0)
        face.play("nod", t)
        var closed = false
        repeat(600) {
            t += 1.0 / 60
            frame = face.tick(t)
            if (frame.openLeft < 0.3) closed = true
        }
        assertTrue(closed, "he blinked")
        assertEquals("neutral", face.emotion, "the happy face was held a second, then let go")
        face.setState("offline")
        repeat(120) {
            t += 1.0 / 60
            frame = face.tick(t)
        }
        assertTrue(frame.offline)
        assertTrue(frame.glow < 1.0)
    }
}
