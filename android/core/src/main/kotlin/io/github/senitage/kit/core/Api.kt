package io.github.senitage.kit.core

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull

/**
 * What Kit's brain sends and takes (docs/5 Reference/API.md). Fields are only ever
 * added on the brain's side, so everything here has a default and unknown fields
 * are skipped: an old app keeps working with a newer Kit.
 */
val KitJson = Json {
    ignoreUnknownKeys = true
    isLenient = true
    explicitNulls = false
    coerceInputValues = true
    encodeDefaults = true
}

/** This app's kind of body, and what it can do in this version (kit.body_registry). */
object PhoneBody {
    const val KIND = "phone"
    const val CHANNEL = "phone"

    /** Phase 1: a screen he's drawn on, a buzz, and a face you can tap. No voice yet. */
    val ABILITIES = listOf("screen", "haptics", "touch")

    /** The looks this app can draw: the 3D face page, and the 2D glow look. */
    val FACES = listOf("model", "glow")
}

@Serializable
data class Health(val ok: Boolean = false, val name: String = "Kit", val version: String = "")

@Serializable
data class PairAnswer(val name: String = "", val kind: String = "", val token: String = "")

@Serializable
data class Hello(
    val id: String = "",
    val kind: String = PhoneBody.KIND,
    val name: String = "",
    val app: String = "",
    val api: Int = 1,
    val abilities: List<String> = PhoneBody.ABILITIES,
    val faces: List<String> = PhoneBody.FACES,
)

@Serializable
data class FaceChoice(
    val character: String = "",
    val style: String = "glow",
    val page: String = "/face/?app=phone",
)

@Serializable
data class HelloAnswer(
    val api: Int = 1,
    val kit: String = "",
    val name: String = "Kit",
    val features: Map<String, Int> = emptyMap(),
    val events: List<String> = emptyList(),
    val face: FaceChoice = FaceChoice(),
    @SerialName("unknown_abilities") val unknownAbilities: List<String> = emptyList(),
) {
    /** Whether the brain offers [feature] at [version] or newer. */
    fun has(feature: String, version: Int = 1): Boolean = (features[feature] ?: 0) >= version
}

@Serializable
data class Segment(val say: String = "", val gesture: String = "none")

@Serializable
data class Reply(
    val segments: List<Segment> = emptyList(),
    val emotion: String = "neutral",
    val detail: String = "",
) {
    /** What he said, as one line. */
    val text: String get() = segments.map { it.say.trim() }.filter { it.isNotEmpty() }.joinToString(" ")
}

/** One message of the conversation, as `/api/messages` gives it. */
@Serializable
data class Message(
    val id: Long = 0,
    val at: String = "",
    val role: String = "",
    val text: String = "",
    val source: String? = null,
    val channel: String? = null,
    val reply: Reply? = null,
    val meta: JsonObject? = null,
) {
    val fromDan: Boolean get() = role == "user"

    /** The body or channel it came through, for marking messages from the desk. */
    fun metaString(key: String): String? = (meta?.get(key) as? JsonPrimitive)?.contentOrNull
}

@Serializable
data class Feeling(val name: String = "", val why: String = "")

@Serializable
data class Dials(val arousal: Double = 0.5, val valence: Double = 0.0)

/** The parts of `/api/life` the phone shows. */
@Serializable
data class LifeState(
    val mood: String = "",
    val face: String = "",
    val feeling: Feeling? = null,
    val doing: String? = null,
    val dials: Dials? = null,
    @SerialName("last_event") val lastEvent: Long = 0,
)

@Serializable
data class LifeEvents(val events: List<JsonObject> = emptyList(), val last: Long = 0)
