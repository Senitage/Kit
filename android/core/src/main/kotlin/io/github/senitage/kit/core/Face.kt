package io.github.senitage.kit.core

import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.exp
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt
import kotlin.math.sin
import kotlin.random.Random

/** One frame of Kit's face, ready to paint. Units are relative to the face size. */
data class FaceFrame(
    val openLeft: Double,
    val openRight: Double,
    val squint: Double,
    val tilt: Double,
    val size: Double,
    val lookX: Double,
    val lookY: Double,
    val blush: Double,
    val glow: Double,
    val talk: Double,
    val offline: Boolean,
    val dx: Double,
    val dy: Double,
    val rot: Double,
    val sx: Double,
    val sy: Double,
    val scale: Double,
    val mouth: Double = 0.0,
    val mouthOpen: Double = 0.0,
    val mouthO: Double = 0.0,
    val brow: Double = 0.0,
    val browUp: Double = 0.0,
    val colour: String? = null,
)

val FACE_STATES = setOf("idle", "sleeping", "listening", "thinking", "speaking", "working", "offline")

/**
 * Kit's face: turns emotions, gestures and states into face numbers every frame.
 * A port of kit.face.rig, so the phone's Kit moves like the desk's. Three layers:
 * reflexes (blinks, darts, breathing), the emotion's pose, and gestures on top.
 * Time is passed in (seconds) and randomness is injected, so tests can drive it.
 */
class Face(
    var character: Character,
    private val rng: Random = Random.Default,
    private val easeS: Double = 0.11,
    private val lookHoldS: Double = 3.0,
) {
    var emotion = "neutral"
        private set
    var resting = "neutral"
        private set
    var state = "idle"
        private set

    /** The gesture playing and when it started, so a copy (the 3D page) can tell a new one. */
    var clip: Pair<String, Double>? = null
        private set

    /** Where [lookAt] last pointed him: x, y and until when. */
    var looking: Triple<Double, Double, Double>? = null
        private set

    var arousal = 0.5
        private set
    var valence = 0.0
        private set

    private var target: Map<String, Double> = character.pose("neutral")
    private val cur = target.toMutableMap()
    private var emotionUntil: Double? = null
    private var last: Double? = null
    private var blinkAt: Double? = null
    private var blinkStart: Double? = null
    private var double = false
    private var dart = 0.0 to 0.0
    private var dartAt = 0.0
    private var glow = 1.0
    private val dials = doubleArrayOf(0.5, 0.0)
    private var breath: Double? = null
    private var colour: DoubleArray? = null

    fun setEmotion(name: String, now: Double, holdS: Double? = null) {
        if (name !in character.emotions) return
        emotion = name
        target = character.pose(name)
        emotionUntil = holdS?.let { now + it }
    }

    fun play(gesture: String, now: Double) {
        if (gesture !in character.gestures) return
        clip = if (gesture == "none") null else gesture to now
    }

    fun setState(name: String) {
        if (name in FACE_STATES) state = name
    }

    fun setDials(arousal: Double, valence: Double) {
        this.arousal = arousal.coerceIn(0.0, 1.0)
        this.valence = valence.coerceIn(-1.0, 1.0)
    }

    /** The face he wears between replies: his mood. A reply's emotion settles back here. */
    fun rest(name: String, now: Double) {
        if (name !in character.emotions || name == resting) return
        val was = resting
        resting = name
        if (emotionUntil == null && emotion == was) setEmotion(name, now)
    }

    fun lookAt(x: Double, y: Double, now: Double) {
        looking = Triple(x.coerceIn(-1.0, 1.0), y.coerceIn(-1.0, 1.0), now + lookHoldS)
    }

    fun tick(now: Double): FaceFrame {
        val dt = last?.let { (now - it).coerceIn(0.0, 0.1) } ?: 0.0
        last = now
        emotionUntil?.let { if (now >= it) setEmotion(resting, now) }

        val wanted = character.statePose(state, emotion, target)
        val a = if (dt > 0) 1 - exp(-dt / easeS) else 0.0
        for ((k, v) in wanted) cur[k] = (cur[k] ?: v) + (v - (cur[k] ?: v)) * a
        easeColour(dt)
        val glowTarget = character.stateGlow(state)
        glow += (glowTarget - glow) * (if (dt > 0) 1 - exp(-dt / 0.4) else 0.0)

        val k = if (dt > 0) 1 - exp(-dt / 2.0) else 0.0
        dials[0] += (arousal - dials[0]) * k
        dials[1] += (valence - dials[1]) * k
        val g = scaled(gesture(now), 0.7 + 0.6 * dials[0])
        val (gazeX, gazeY) = gaze(now)
        val period = if (state == "sleeping") 7.0 else 4.2 * (1 + (0.5 - dials[0]) * 0.6)
        val b = (breath ?: (now * 2 * PI / period)) + dt * 2 * PI / period
        breath = b
        val breathing = sin(b)
        val blink = blink(now)
        fun c(key: String) = cur[key] ?: 0.0
        val open = max(0.0, (c("open") + g.getValue("open")) * blink)
        val talk = if (state == "speaking") 0.25 + 0.55 * abs(sin(now * 11.8) * sin(now * 18.9 + 1)) else 0.0
        return FaceFrame(
            openLeft = open * max(0.0, 1 + c("asym") * 0.45),
            openRight = open * max(0.0, 1 - c("asym") * 0.45) * (1 - g.getValue("wink")),
            squint = (c("squint") + g.getValue("squint")).coerceIn(0.0, 0.95),
            tilt = c("tilt"),
            size = c("size") + g.getValue("size"),
            lookX = (gazeX + g.getValue("look_x")).coerceIn(-1.0, 1.0),
            lookY = (gazeY + g.getValue("look_y")).coerceIn(-1.0, 1.0),
            blush = (c("blush") + 0.15 * dials[1]).coerceIn(0.0, 1.0),
            glow = glow,
            talk = talk,
            offline = state == "offline",
            dx = g.getValue("dx"),
            dy = c("head_y") + g.getValue("dy") + breathing * 0.005,
            rot = c("head_tilt") + g.getValue("rot"),
            sx = g.getValue("sx") * (1 - breathing * 0.006),
            sy = g.getValue("sy") * (1 + breathing * 0.012),
            scale = g.getValue("scale"),
            mouth = c("mouth"),
            mouthOpen = c("mouth_open"),
            mouthO = c("mouth_o"),
            brow = c("brow"),
            browUp = c("brow_up"),
            colour = colour?.let { hex(it) },
        )
    }

    private fun easeColour(dt: Double) {
        val shown = character.statePoseName(state, emotion)
        val hex = character.moodColour(shown)
        if (hex == null || hex.length != 7) {
            colour = null
            return
        }
        val rgb = doubleArrayOf(
            hex.substring(1, 3).toInt(16).toDouble(),
            hex.substring(3, 5).toInt(16).toDouble(),
            hex.substring(5, 7).toInt(16).toDouble(),
        )
        val now = colour
        if (now == null || dt <= 0) {
            if (now == null) colour = rgb
            return
        }
        val a = 1 - exp(-dt / 0.35)
        for (i in 0..2) now[i] += (rgb[i] - now[i]) * a
    }

    private fun gesture(now: Double): Map<String, Double> {
        val (name, start) = clip ?: return NO_MOVE
        val seconds = character.gestureSeconds(name)
        val t = if (seconds > 0) (now - start) / seconds else 1.0
        if (t >= 1) {
            clip = null
            return NO_MOVE
        }
        return character.gestureAt(name, max(t, 0.0))
    }

    private fun gaze(now: Double): Pair<Double, Double> {
        val x = cur["look_x"] ?: 0.0
        val y = cur["look_y"] ?: 0.0
        if (state == "sleeping") return x to y
        if (state == "working") return -0.6 + 1.2 * ((now / 1.6) % 1) to 0.3
        val look = looking
        if (look != null && now < look.third && state != "thinking") return look.first to look.second
        if (now >= dartAt) {
            val far = rng.nextDouble() < 0.25 && state != "listening"
            val reachX = if (far) 0.9 else 0.35
            val reachY = if (far) 0.6 else 0.25
            dart = rng.nextDouble(-1.0, 1.0) * reachX to rng.nextDouble(-1.0, 1.0) * reachY
            dartAt = now + rng.nextDouble(0.9, 3.7)
        }
        return x + dart.first to y + dart.second
    }

    private fun blink(now: Double): Double {
        if ((state == "sleeping" || state == "offline") && blinkStart == null) {
            blinkAt = null
            return 1.0
        }
        val at = blinkAt ?: (now + rng.nextDouble(1.0, 3.0)).also { blinkAt = it }
        if (blinkStart == null && now >= at) {
            blinkStart = now
            double = rng.nextDouble() < 0.2
        }
        val start = blinkStart ?: return 1.0
        val length = if (double) 0.42 else 0.17
        val t = (now - start) / length
        if (t >= 1) {
            blinkStart = null
            val slower = 1 + (0.5 - dials[0]) * 0.8
            blinkAt = now + rng.nextDouble(2.0, 6.2) * slower
            return 1.0
        }
        val phase = if (double) (t * 2) % 1 else t
        return 1 - sin(PI * phase)
    }

    companion object {
        private val NO_MOVE: Map<String, Double> =
            Character.CHANNELS.associateWith { if (it == "sx" || it == "sy" || it == "scale") 1.0 else 0.0 }

        private fun scaled(g: Map<String, Double>, k: Double): Map<String, Double> {
            if (k == 1.0) return g
            return g.mapValues { (name, v) ->
                when (name) {
                    "sx", "sy", "scale" -> 1 + (v - 1) * k
                    "wink" -> v
                    else -> v * k
                }
            }
        }

        private fun hex(rgb: DoubleArray): String = "#" + rgb.joinToString("") {
            "%02x".format(min(255, max(0, it.roundToInt())))
        }
    }
}
