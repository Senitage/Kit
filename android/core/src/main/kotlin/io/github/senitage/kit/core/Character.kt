package io.github.senitage.kit.core

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.jsonObject
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.min
import kotlin.math.pow
import kotlin.math.sin

/**
 * Kit's character sheet, as `/api/face` sends it: his looks, a pose for every
 * emotion, how each state bends it, and every gesture as a set of moves. A port of
 * kit.face.character, so the phone draws and moves him with the same numbers as
 * the desk. See docs/3 Deep Dives/Face In Depth.md.
 */
class Character(val sheet: JsonObject) {
    val name: String get() = sheet.str("name") ?: "Kit"

    private val poses: JsonObject = sheet.obj("poses") ?: JsonObject(emptyMap())
    private val poseDefault: JsonObject = sheet.obj("pose_default") ?: JsonObject(emptyMap())
    private val states: JsonObject = sheet.obj("states") ?: JsonObject(emptyMap())
    private val gestureSheet: JsonObject = sheet.obj("gestures") ?: JsonObject(emptyMap())

    val emotions: Set<String> get() = poses.keys
    val gestures: Set<String> get() = gestureSheet.keys

    /** The look [app] should draw, given the [styles] it can draw (its 2D fallback if need be). */
    fun look(app: String = PhoneBody.KIND, styles: Set<String> = setOf("glow")): JsonObject? {
        val looks = sheet.obj("looks") ?: return null
        val use = sheet.obj("use") ?: return null
        val name = use.str(app) ?: use.str("default") ?: return null
        var chosen = looks.obj(name) ?: return null
        if (chosen.str("style") !in styles) {
            chosen = chosen.str("fallback")?.let { looks.obj(it) } ?: return null
        }
        return if (chosen.str("style") in styles) chosen else null
    }

    /** An emotion's pose with every key filled in from the defaults. */
    fun pose(emotion: String): Map<String, Double> {
        val out = FEATURE_POSE_KEYS.associateWith { 0.0 }.toMutableMap()
        out.putAll(numbers(poseDefault))
        poses.obj(emotion)?.let { out.putAll(numbers(it)) }
        return out
    }

    fun moodColour(pose: String): String? {
        val colours = sheet.obj("mood_colours") ?: return null
        return colours.str(pose) ?: colours.str("neutral")
    }

    val hasMoodColours: Boolean get() = (sheet.obj("mood_colours")?.size ?: 0) > 0

    fun gestureSeconds(gesture: String): Double =
        gestureSheet.obj(gesture)?.num("seconds") ?: 0.0

    fun gestureAt(gesture: String, t: Double): Map<String, Double> =
        moveAt(gestureSheet.obj(gesture)?.obj("moves") ?: JsonObject(emptyMap()), t)

    /** [pose] (the emotion's) as [state] bends it: asleep, offline, listening... */
    fun statePose(state: String, emotion: String, pose: Map<String, Double>): Map<String, Double> {
        val rule = states.obj(state) ?: return pose
        var out = pose
        rule.str("pose")?.let { name ->
            val only = rule.str("only_from")
            if (only != null && emotion != only) return pose
            out = pose(name)
        }
        val bent = out.toMutableMap()
        rule.obj("add")?.let { add -> numbers(add).forEach { (k, v) -> bent[k] = (bent[k] ?: 0.0) + v } }
        rule.obj("set")?.let { set -> bent.putAll(numbers(set)) }
        return bent
    }

    /** The pose whose colour a state shows (asleep and offline pick their own). */
    fun statePoseName(state: String, emotion: String): String {
        val rule = states.obj(state) ?: return emotion
        val pose = rule.str("pose") ?: return emotion
        val only = rule.str("only_from")
        return if (only == null || only == emotion) pose else emotion
    }

    fun stateGlow(state: String): Double = states.obj(state)?.num("glow") ?: 1.0

    companion object {
        val CORE_POSE_KEYS = listOf("open", "squint", "tilt", "asym", "size", "look_x", "look_y", "blush", "head_tilt", "head_y")
        val FEATURE_POSE_KEYS = listOf("mouth", "mouth_open", "mouth_o", "brow", "brow_up")
        val CHANNELS = listOf("dx", "dy", "rot", "sx", "sy", "scale", "look_x", "look_y", "open", "squint", "size", "wink")
        private val ONE_BASED = setOf("sx", "sy", "scale")

        fun parse(text: String): Character = Character(KitJson.parseToJsonElement(text).jsonObject)

        private fun numbers(obj: JsonObject): Map<String, Double> =
            obj.mapNotNull { (k, v) -> (v as? JsonPrimitive)?.doubleOrNull?.let { k to it } }.toMap()

        private fun ease(t: Double): Double = if (t < 0.5) 2 * t * t else 1 - (-2 * t + 2).pow(2) / 2

        private fun shape(t: Double, shape: JsonArray): Double {
            val name = (shape.getOrNull(0) as? JsonPrimitive)?.contentOrNull ?: return 0.0
            val args = shape.drop(1).map { (it as? JsonPrimitive)?.doubleOrNull ?: 0.0 }
            return when (name) {
                "bump" -> {
                    val a = args[0]
                    val b = args[1]
                    val v = if (t < a || t > b) 0.0 else sin(PI * (t - a) / (b - a))
                    if (args.size > 2) min(1.0, v * args[2]) else v
                }
                "hold" -> {
                    val rise = args[0]
                    val fall = args[1]
                    when {
                        t < rise -> ease(t / rise)
                        t > fall -> 1 - ease((t - fall) / (1 - fall))
                        else -> 1.0
                    }
                }
                "sin" -> sin(PI * args[0] * t)
                "abs_sin" -> abs(sin(PI * args[0] * t))
                "line" -> args[0] + args[1] * t
                "jolt" -> {
                    val at = args[0]
                    if (t < at) t / at else 1 - ease((t - at) / (1 - at))
                }
                else -> 0.0
            }
        }

        /** Every channel's value for a gesture's moves at time [t] (0..1). */
        fun moveAt(moves: JsonObject, t: Double): Map<String, Double> {
            val out = CHANNELS.associateWith { if (it in ONE_BASED) 1.0 else 0.0 }.toMutableMap()
            for ((channel, terms) in moves) {
                for (term in terms as? JsonArray ?: continue) {
                    val parts = term as? JsonArray ?: continue
                    var v = (parts.getOrNull(0) as? JsonPrimitive)?.doubleOrNull ?: continue
                    for (s in parts.drop(1)) v *= shape(t, s as? JsonArray ?: continue)
                    out[channel] = (out[channel] ?: 0.0) + v
                }
            }
            return out
        }
    }
}
