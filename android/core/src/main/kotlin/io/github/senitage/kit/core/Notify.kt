package io.github.senitage.kit.core

/** The source Kit's brain gives a message he said of his own accord (kit.brain.PIPE_UP). */
const val PIPE_UP_SOURCE = "pipe_up"

/**
 * A nudge from Kit's brain through the push service (kit.push): content-free, only
 * what it's about and, for a pipe-up, the message's id to fetch.
 */
data class Nudge(val about: String, val messageId: Long?) {
    val pipeUp: Boolean get() = about == "pipe_up"

    companion object {
        fun from(data: Map<String, String>): Nudge? {
            val about = data["kit"]?.takeIf { it.isNotBlank() } ?: return null
            return Nudge(about, data["id"]?.toLongOrNull())
        }
    }
}

/**
 * Which of the messages caught up since the phone last looked are pipe-ups worth a
 * notification: his own lines (not answers to Dan) after [after], oldest first. A
 * backlog is cut to the last [most], so a phone that was off for a week isn't buried.
 */
fun newPipeUps(messages: List<Message>, after: Long, most: Int = 3): List<Message> =
    messages
        .filter { it.id > after && !it.fromDan && it.source == PIPE_UP_SOURCE && it.text.isNotBlank() }
        .sortedBy { it.id }
        .takeLast(most)

/**
 * The latest message id the phone has seen, after a catch-up: the newest of what
 * it had and what came, so the next look starts there.
 */
fun seenUpTo(messages: List<Message>, before: Long): Long =
    maxOf(before, messages.maxOfOrNull { it.id } ?: 0L)
