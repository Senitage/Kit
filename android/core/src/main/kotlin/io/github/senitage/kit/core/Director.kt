package io.github.senitage.kit.core

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlin.math.roundToLong
import kotlin.random.Random

/** One timed step of acting out a reply: set the emotion, play a gesture, say words. */
data class Cue(val at: Double, val kind: String, val value: String = "", val seconds: Double = 0.0)

/**
 * A reply as timed cues for the face (kit.face.rig.plan_reply): each gesture a beat
 * before its words, and the words' length guessed from the text (there's no voice
 * on the phone yet to keep the time).
 */
fun planReply(reply: Reply, secondsPerChar: Double = 0.06, leadS: Double = 0.25, gapS: Double = 0.45): List<Cue> {
    val cues = mutableListOf(Cue(0.0, "emotion", reply.emotion))
    var t = 0.0
    for (seg in reply.segments) {
        if (seg.gesture != "none") cues += Cue(t, "gesture", seg.gesture)
        val speak = seg.say.length * secondsPerChar
        cues += Cue(t + leadS, "say", seg.say, speak)
        t += leadS + speak + gapS
    }
    cues += Cue(t, "done")
    return cues
}

/**
 * Acts Kit out on the phone: chat answers (as [Cues]), his life events, being out
 * of reach, and being tapped. It moves one [Face]; the 2D painter draws it and
 * [Mirror] copies it to the 3D face page, the same split as the desk app.
 */
class Director(
    private val scope: CoroutineScope,
    val face: Face,
    private val now: () -> Double,
    private val rng: Random = Random.Default,
) : Cues {
    /** A show (the time, the weather) for whichever face is on screen. */
    var onShow: (JsonObject) -> Unit = {}

    /** A little buzz to go with a moment: "boop", "pat", "pipe_up". */
    var onBuzz: (String) -> Unit = {}

    private val _bubble = MutableStateFlow("")

    /** What his bubble says: his words as he says them, or what he's up to. */
    val bubble: StateFlow<String> = _bubble.asStateFlow()

    private var acting: Job? = null
    private var answered = false
    private var heldShow: JsonObject? = null
    private var asleep = false
    private var online = true
    private var inTurn = false
    private var doing = ""
    private var hush = ""

    // ---- the chat ----

    override fun heard() {
        inTurn = true
        answered = false
        heldShow = null
        acting?.cancel()
        if (asleep) wake()
        face.play("nod", now())
        state("thinking")
    }

    override fun mood(emotion: String) {
        face.setEmotion(emotion, now(), holdS = 30.0)
    }

    override fun working() = state("working")

    override fun words() = state("speaking")

    override fun reply(reply: Reply, pipeUp: Boolean) {
        if (pipeUp) {
            if (asleep) wake()
            face.play("perk_up", now())
            onBuzz("pipe_up")
            acting?.cancel()
            acting = scope.launch {
                delay(700)
                perform(reply)
            }
        } else {
            acting?.cancel()
            acting = scope.launch { perform(reply) }
        }
    }

    override fun show(show: JsonObject) {
        if (answered) onShow(show) else heldShow = show
    }

    override fun error() {
        face.play("shrug", now())
        state("idle")
    }

    override fun idle() {
        inTurn = false
        if (acting?.isActive != true && face.state != "offline") state(if (asleep) "sleeping" else "idle")
    }

    private suspend fun perform(reply: Reply) {
        val cues = planReply(reply)
        val estimate = cues.last().at
        val started = now()
        for (cue in cues) {
            val wait = cue.at - (now() - started)
            if (wait > 0) delay((wait * 1000).roundToLong())
            when (cue.kind) {
                "emotion" -> face.setEmotion(cue.value, now(), holdS = 2 * estimate + 4)
                "gesture" -> face.play(cue.value, now())
                "say" -> {
                    if (face.state != "offline") state("speaking")
                    _bubble.value = cue.value
                    if (!answered) {
                        answered = true
                        heldShow?.let { onShow(it) }
                        heldShow = null
                    }
                    if (cue.seconds > 0) {
                        delay((cue.seconds * 1000).roundToLong())
                        if (face.state == "speaking") state("idle")
                    }
                }
                "done" -> {
                    if (face.state == "speaking" || face.state == "thinking" || face.state == "working") state("idle")
                    delay(BUBBLE_HOLD_MS)
                    _bubble.value = idleText()
                }
            }
        }
    }

    // ---- his life ----

    /** A life event from `/api/life/events` (pipe-ups go through the chat). */
    fun life(event: LifeEvent) {
        val t = now()
        when (event.type) {
            "state" -> when (event.str("state")) {
                "asleep" -> fallAsleep()
                "awake" -> wake()
            }
            "fidget" -> if (!busy() && !asleep) face.play(event.str("gesture") ?: "look_away", t)
            "look" -> if (!asleep) face.lookAt(event.num("x") ?: 0.0, event.num("y") ?: 0.0, t)
            "react" -> if (!asleep) face.play(event.str("gesture") ?: "perk_up", t)
            "mood" -> face.rest(event.str("face") ?: "neutral", t)
            "dials" -> face.setDials(event.num("arousal") ?: 0.5, event.num("valence") ?: 0.0)
            "doing" -> {
                doing = event.str("what") ?: ""
                if (!busy()) _bubble.value = idleText()
            }
            "quiet" -> {
                hush = event.str("bubble") ?: ""
                if (!busy()) _bubble.value = idleText()
            }
        }
    }

    /** How he is when the app opens (`/api/life`). */
    fun start(life: LifeState) {
        if (life.mood == "asleep") fallAsleep()
        if (life.face.isNotEmpty()) face.rest(life.face, now())
        life.dials?.let { face.setDials(it.arousal, it.valence) }
        doing = life.doing ?: ""
        if (!busy()) _bubble.value = idleText()
    }

    fun setOnline(on: Boolean) {
        if (on == online) return
        online = on
        if (!on) {
            acting?.cancel()
            state("offline")
            _bubble.value = ""
        } else {
            state(if (asleep) "sleeping" else "idle")
            _bubble.value = idleText()
        }
    }

    // ---- being tapped ----

    /** A tap on his face: a boop. */
    fun boop() {
        if (!online) return
        if (asleep) {
            face.play("startle", now())
            onBuzz("boop")
            return
        }
        face.play(BOOPS[rng.nextInt(BOOPS.size)], now())
        onBuzz("boop")
    }

    /** The phone was shaken: he's startled. */
    fun shaken() {
        if (!online) return
        face.play("startle", now())
        onBuzz("boop")
    }

    /** A long press on his face: a pat on the head. */
    fun pat() {
        if (!online) return
        face.setEmotion("fond", now(), holdS = 3.0)
        face.play("wiggle", now())
        onBuzz("pat")
    }

    // ---- helpers ----

    private fun busy(): Boolean = inTurn || acting?.isActive == true ||
        face.state == "speaking" || face.state == "thinking" || face.state == "working"

    private fun fallAsleep() {
        asleep = true
        if (face.state != "offline") state("sleeping")
    }

    private fun wake() {
        asleep = false
        if (face.state == "sleeping") state("idle")
    }

    private fun state(name: String) {
        if (!online && name != "offline") return
        face.setState(name)
    }

    private fun idleText(): String = when {
        doing.isNotEmpty() -> "$doing..."
        hush.isNotEmpty() -> "$hush..."
        else -> ""
    }

    companion object {
        private val BOOPS = listOf("perk_up", "wiggle", "bounce", "double_take", "tilt_head")
        const val BUBBLE_HOLD_MS = 6000L
    }
}

/**
 * Copies what a [Face] is doing to Kit's 3D face page as calls to its `kit` API
 * (src/kit/web/face/kit3d.js), sending only what changed: kit.desk.face3d.Mirror.
 */
class Mirror(private val face: Face) {
    private var emotion: String? = null
    private var state: String? = null
    private var clip: Pair<String, Double>? = face.clip
    private var look: Triple<Double, Double, Double>? = null
    private var dials: Pair<Double, Double>? = null

    /** Send everything again next time (the page reloaded). */
    fun reset() {
        emotion = null
        state = null
        clip = face.clip
        look = null
        dials = null
    }

    fun calls(): List<String> {
        val out = mutableListOf<String>()
        if (face.emotion != emotion) {
            emotion = face.emotion
            out += call("setEmotion", quote(face.emotion))
        }
        if (face.state != state) {
            state = face.state
            out += call("setState", quote(face.state))
        }
        val playing = face.clip
        if (playing != null && playing != clip) out += call("play", quote(playing.first))
        clip = playing
        val looking = face.looking
        if (looking != null && looking != look) {
            look = looking
            out += call("lookAt", round3(looking.first), round3(looking.second))
        }
        val now = round2(face.arousal) to round2(face.valence)
        if (now != dials) {
            dials = now
            out += call("setDials", now.first.toString(), now.second.toString())
        }
        return out
    }

    companion object {
        fun call(name: String, vararg args: String): String = "kit.$name(${args.joinToString(", ")});"

        fun quote(text: String): String = JsonPrimitive(text).toString()

        /** A show from the brain for the page's `kit.show`. */
        fun show(show: JsonObject): String = call("show", show.toString())

        private fun round2(v: Double) = Math.round(v * 100) / 100.0

        private fun round3(v: Double) = (Math.round(v * 1000) / 1000.0).toString()
    }
}
