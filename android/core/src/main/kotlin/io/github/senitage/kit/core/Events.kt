package io.github.senitage.kit.core

import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.decodeFromJsonElement
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.longOrNull

/** One event of a chat answer as it streams in, one JSON object per line. */
sealed interface ChatEvent {
    /** The brain has the message: from here on it won't be lost, even if the line drops. */
    data object Accepted : ChatEvent

    /** His feeling going in, so the face reacts at once. */
    data class Mood(val emotion: String) : ChatEvent

    /** Words as they're written. */
    data class Say(val text: String, val cloud: Boolean) : ChatEvent

    /** Something for his face to show: the time, the date, the weather. */
    data class Show(val show: JsonObject) : ChatEvent

    /** He's doing something mid-answer: remembering, looking at the PC... */
    data class Doing(val what: String) : ChatEvent

    /** A bigger model is taking over ("Let me think..."). */
    data class HandingOff(val to: String) : ChatEvent

    /** A line for the chat that isn't him talking: a budget warning, a fact learned. */
    data class Note(val text: String) : ChatEvent

    /** The whole reply. */
    data class Done(val reply: Reply, val cloud: Boolean, val messageId: Long?) : ChatEvent

    /** Something went wrong, in words. */
    data class Error(val message: String) : ChatEvent

    /** Anything this app doesn't know yet (a sound for his voice, a newer event). */
    data class Other(val type: String) : ChatEvent

    companion object {
        /** One line of the stream; null for a blank or broken line. */
        fun parse(line: String): ChatEvent? {
            if (line.isBlank()) return null
            val obj = try {
                KitJson.parseToJsonElement(line).jsonObject
            } catch (e: Exception) {
                return null
            }
            return from(obj)
        }

        fun from(e: JsonObject): ChatEvent {
            val type = e.str("type") ?: ""
            return when (type) {
                "mood" -> Mood(e.str("emotion") ?: "neutral")
                "say" -> Say(e.str("text") ?: "", e.str("source") == "cloud")
                "show" -> (e["show"] as? JsonObject)?.let { Show(it) } ?: Other(type)
                "recalled" -> Doing("remembering")
                "reading_note" -> Doing("reading your notes")
                "looked_at_pc" -> Doing("looking at your PC")
                "looked_around" -> Doing("looking around")
                "weather" -> Doing("checking the weather")
                "handing_off" -> HandingOff(e.str("to") ?: "the cloud")
                "notice" -> Note(e.str("message") ?: "")
                "remembered" -> {
                    val label = when (e.str("decision")) {
                        "same" -> "Already knew"
                        "update" -> "Updated memory"
                        else -> "Remembered"
                    }
                    Note("$label: ${e.str("fact") ?: ""}")
                }
                "thing_suggested" -> Note("Add to the register? ${e.obj("thing")?.str("line") ?: ""} (yes or no)")
                "thing_updated" -> e.obj("thing")?.str("line")?.let { Note("Updated the register: $it") } ?: Other(type)
                "new_topic" -> Note(e.str("message") ?: "New topic, so Kit started fresh.")
                "reply" -> Done(
                    e["reply"]?.let { decodeReply(it) } ?: Reply(),
                    e.str("source") == "cloud",
                    (e["message_id"] as? JsonPrimitive)?.longOrNull,
                )
                "error" -> Error(e.str("message") ?: "Something went wrong.")
                else -> Other(type)
            }
        }
    }
}

fun decodeReply(element: JsonElement): Reply? = try {
    KitJson.decodeFromJsonElement<Reply>(element)
} catch (e: Exception) {
    null
}

fun JsonObject.str(key: String): String? = (this[key] as? JsonPrimitive)?.contentOrNull

fun JsonObject.num(key: String): Double? = (this[key] as? JsonPrimitive)?.contentOrNull?.toDoubleOrNull()

fun JsonObject.obj(key: String): JsonObject? = this[key] as? JsonObject

/** One event from `/api/life/events`: a fidget, his mood, a pipe-up... */
data class LifeEvent(val id: Long, val type: String, val data: JsonObject) {
    fun str(key: String): String? = data.str(key)

    fun num(key: String): Double? = data.num(key)

    /** A pipe-up's line. */
    val reply: Reply? get() = data["reply"]?.let { decodeReply(it) }

    companion object {
        fun from(e: JsonObject): LifeEvent = LifeEvent(
            (e["id"] as? JsonPrimitive)?.longOrNull ?: 0,
            e.str("type") ?: "",
            e,
        )
    }
}
