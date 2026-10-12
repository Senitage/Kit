package io.github.senitage.kit.core

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.Serializable
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.JsonObject
import java.time.Duration
import java.time.OffsetDateTime
import java.util.TreeMap
import java.util.UUID

/** Somewhere small to keep text between runs (the app's files folder; memory in tests). */
interface Store {
    fun read(name: String): String?

    fun write(name: String, text: String)
}

class MemoryStore : Store {
    val files = mutableMapOf<String, String>()

    override fun read(name: String): String? = files[name]

    override fun write(name: String, text: String) {
        files[name] = text
    }
}

enum class Who { DAN, KIT, NOTE, ERROR }

enum class Sending { DONE, SENDING, WAITING, FAILED }

/** One line of the chat as the screen shows it. */
data class Line(
    val key: String,
    val who: Who,
    val text: String,
    val detail: String = "",
    val at: String = "",
    val channel: String? = null,
    val cloud: Boolean = false,
    val sending: Sending = Sending.DONE,
    val problem: String = "",
    val writing: Boolean = false,
    val outgoing: String? = null,
)

data class ChatView(
    val lines: List<Line> = emptyList(),
    val older: Boolean = true,
    val loadingOlder: Boolean = false,
    val typing: Boolean = false,
    val doing: String? = null,
)

/** A message typed on the phone that hasn't reached Kit yet. Kept on the phone. */
@Serializable
data class Outgoing(
    val id: String,
    val text: String,
    val writtenAt: String,
    val spoken: Boolean = false,
    val failed: String? = null,
)

/** What the chat tells Kit's face as an answer comes in (see [Director]). */
interface Cues {
    fun heard() {}

    fun mood(emotion: String) {}

    fun working() {}

    fun words() {}

    fun reply(reply: Reply, pipeUp: Boolean = false) {}

    fun show(show: JsonObject) {}

    fun error() {}

    fun idle() {}
}

/**
 * The one conversation, as the phone shows it: Kit's history (the truth, from
 * `/api/messages`), the answer streaming in now, and messages waiting to be sent.
 *
 * A message typed while Kit's out of reach goes into the outbox and waits; it's
 * sent with the time it was written once he's back. Once a turn is over the
 * history is caught up and the live lines give way to the saved ones.
 */
class Conversation(
    private val scope: CoroutineScope,
    private val store: Store,
    private val clock: () -> OffsetDateTime = { OffsetDateTime.now() },
    private val newId: () -> String = { UUID.randomUUID().toString() },
) {
    var client: KitClient? = null
    var body: String = ""
    var cues: Cues = object : Cues {}

    /** Told when a call finds Kit unreachable or the token refused. */
    var trouble: (KitError) -> Unit = {}

    private val _view = MutableStateFlow(ChatView())
    val view: StateFlow<ChatView> = _view.asStateFlow()

    private val lock = Mutex()
    private val history = TreeMap<Long, Message>()
    private val notes = mutableListOf<Pair<Long, Line>>() // lines never saved by Kit, after a message id
    private val outbox = mutableListOf<Outgoing>()
    private val turns = mutableListOf<Turn>() // the turn being answered, and ones not caught up yet
    private var older = true
    private var loadingOlder = false
    private var online = false
    private var pumping: Job? = null
    private var noteCount = 0

    private class Turn(val key: String, val outgoing: Outgoing?, val baseId: Long) {
        val items = mutableListOf<Line>()
        var current: Int? = null // the Kit line words are going into
        var doing: String? = null
        var accepted = false
        var done = false
    }

    // ---- starting and stopping ----

    /** What was kept from last time: the latest history and the outbox. */
    fun load() {
        store.read(HISTORY_FILE)?.let { text ->
            runCatching { KitJson.decodeFromString(ListSerializer(Message.serializer()), text) }
                .getOrNull()?.forEach { history[it.id] = it }
        }
        store.read(OUTBOX_FILE)?.let { text ->
            runCatching { KitJson.decodeFromString(ListSerializer(Outgoing.serializer()), text) }
                .getOrNull()?.let { outbox.addAll(it) }
        }
        publish()
    }

    /** Kit can be reached (or not). Coming back sends whatever waited. */
    fun setOnline(on: Boolean) {
        online = on
        if (on) pump()
        publish()
    }

    // ---- history ----

    /** Bring the history up to date: the latest page, or everything since the last message. */
    suspend fun refresh() {
        val c = client ?: return
        try {
            lock.withLock {
                if (history.isEmpty()) {
                    val page = c.messages(PAGE)
                    page.forEach { history[it.id] = it }
                    older = page.size >= PAGE
                } else {
                    var pages = 0
                    while (true) {
                        val page = c.messages(CATCH_UP, after = history.lastKey())
                        page.forEach { history[it.id] = it }
                        if (page.size < CATCH_UP) break
                        if (++pages >= MAX_CATCH_UP_PAGES) {
                            // Far behind: start again from the latest page.
                            history.clear()
                            notes.clear()
                            c.messages(PAGE).forEach { history[it.id] = it }
                            older = true
                            break
                        }
                    }
                }
                settleTurns()
                save()
            }
        } catch (e: KitError) {
            trouble(e)
        }
        publish()
    }

    /** Scroll back: the page of history before the oldest message shown. */
    suspend fun loadOlder() {
        val c = client ?: return
        if (loadingOlder || !older || history.isEmpty()) return
        loadingOlder = true
        publish()
        try {
            val page = c.messages(PAGE, before = history.firstKey())
            lock.withLock { page.forEach { history[it.id] = it } }
            older = page.size >= PAGE
        } catch (e: KitError) {
            trouble(e)
        } finally {
            loadingOlder = false
            publish()
        }
    }

    /** Start a fresh conversation: he forgets the thread, the history stays. */
    suspend fun newChat() {
        val c = client ?: return
        try {
            c.newChat()
            note("New chat. Kit starts fresh from here.")
        } catch (e: KitError) {
            trouble(e)
        }
    }

    // ---- sending ----

    fun send(text: String, spoken: Boolean = false) {
        val words = text.trim()
        if (words.isEmpty()) return
        outbox += Outgoing(newId(), words, clock().toString(), spoken)
        saveOutbox()
        publish()
        pump()
    }

    fun retry(id: String) {
        val i = outbox.indexOfFirst { it.id == id }
        if (i < 0) return
        outbox[i] = outbox[i].copy(failed = null)
        saveOutbox()
        publish()
        pump()
    }

    fun discard(id: String) {
        outbox.removeAll { it.id == id }
        saveOutbox()
        publish()
    }

    /** How many messages are waiting to be sent. */
    val waiting: Int get() = outbox.count { it.failed == null }

    /** Send what's waiting, one at a time, while Kit can be reached. */
    fun pump(): Job? {
        if (pumping?.isActive == true) return pumping
        pumping = scope.launch {
            while (true) {
                val c = client ?: break
                if (!online) break
                val next = outbox.firstOrNull { it.failed == null } ?: break
                if (!sendOne(c, next)) break
            }
        }
        return pumping
    }

    /**
     * Send what's waiting without the screen (from the background), returning once
     * it's all gone or Kit can't be reached. True when nothing is left waiting.
     */
    suspend fun sendWaiting(): Boolean {
        online = true
        pump()?.join()
        return waiting == 0
    }

    private suspend fun sendOne(c: KitClient, item: Outgoing): Boolean {
        val turn = Turn("t${item.id}", item, lastId())
        turns += turn
        publish()
        cues.heard()
        val written = runCatching { OffsetDateTime.parse(item.writtenAt) }.getOrNull()
        val waited = written != null && Duration.between(written, clock()).seconds > WAITED_S
        var keepGoing = true
        try {
            c.chat(item.text, body = body, sentAt = if (waited) written else null, spoken = item.spoken)
                .collect { event -> onEvent(turn, event) }
        } catch (e: KitError.Broken) {
            add(turn, Line(noteKey(), Who.NOTE, "The line dropped before he finished. His answer is saved, so it shows once he's back."))
        } catch (e: KitError) {
            if (!turn.accepted) {
                turns -= turn
                if (e is KitError.Unreachable || e is KitError.BadToken) {
                    keepGoing = false
                    trouble(e)
                } else {
                    replace(item, item.copy(failed = e.message ?: "Kit couldn't take it"))
                }
            } else {
                add(turn, Line(noteKey(), Who.ERROR, e.message ?: "Something went wrong."))
            }
        } finally {
            turn.done = true
            turn.current = null
            turn.doing = null
            cues.idle()
            publish()
        }
        if (turn.accepted) refresh()
        return keepGoing
    }

    private fun onEvent(turn: Turn, event: ChatEvent) {
        when (event) {
            ChatEvent.Accepted -> {
                turn.accepted = true
                turn.outgoing?.let { sent -> outbox.removeAll { it.id == sent.id } }
                saveOutbox()
            }
            is ChatEvent.Mood -> cues.mood(event.emotion)
            is ChatEvent.Say -> {
                val i = turn.current ?: run {
                    turn.items += Line("${turn.key}-${turn.items.size}", Who.KIT, "", at = now(), cloud = event.cloud, writing = true)
                    turn.items.lastIndex.also { turn.current = it }
                }
                val line = turn.items[i]
                turn.items[i] = line.copy(text = line.text + event.text, cloud = event.cloud)
                turn.doing = null
                cues.words()
            }
            is ChatEvent.Doing -> {
                turn.current = null
                turn.doing = event.what
                cues.working()
            }
            is ChatEvent.HandingOff -> {
                turn.current = null
                turn.doing = "asking ${event.to}"
                cues.working()
            }
            is ChatEvent.Note -> add(turn, Line(noteKey(), Who.NOTE, event.text))
            is ChatEvent.Show -> cues.show(event.show)
            is ChatEvent.Done -> {
                val reply = event.reply
                val words = Line(
                    "${turn.key}-${turn.items.size}",
                    Who.KIT,
                    reply.text,
                    detail = reply.detail,
                    at = now(),
                    cloud = event.cloud,
                )
                val i = turn.current
                if (i != null) {
                    val said = turn.items[i]
                    turn.items[i] = if (reply.text.isEmpty() && reply.detail.isEmpty()) {
                        said.copy(writing = false)
                    } else {
                        words.copy(key = said.key)
                    }
                } else if (reply.text.isNotEmpty() || reply.detail.isNotEmpty()) {
                    turn.items += words
                }
                turn.current = null
                turn.doing = null
                cues.reply(reply)
            }
            is ChatEvent.Error -> {
                add(turn, Line(noteKey(), Who.ERROR, event.message))
                cues.error()
            }
            is ChatEvent.Other -> Unit
        }
        publish()
    }

    // ---- things Kit says by himself ----

    /** A pipe-up from his life events: shown now, and the history catches up after. */
    suspend fun pipeUp(reply: Reply) {
        val turn = Turn("p${newId()}", null, lastId())
        turn.items += Line("${turn.key}-0", Who.KIT, reply.text, detail = reply.detail, at = now())
        turn.done = true
        turns += turn
        publish()
        cues.reply(reply, pipeUp = true)
        refresh()
    }

    /** A line for the chat that Kit doesn't keep ("New chat..."). */
    fun note(text: String, who: Who = Who.NOTE) {
        notes += lastId() to Line(noteKey(), who, text, at = now())
        publish()
    }

    // ---- what the screen shows ----

    private fun publish() {
        val lines = mutableListOf<Line>()
        val byAnchor = notes.groupBy({ it.first }, { it.second })
        byAnchor[0L]?.let { lines += it }
        for ((id, m) in history) {
            lines += line(m)
            byAnchor[id]?.let { lines += it }
        }
        notes.filter { it.first > 0 && it.first !in history }.forEach { lines += it.second }
        var typing = false
        var doing: String? = null
        for (turn in turns) {
            val out = turn.outgoing
            if (out != null && !savedAlready(turn, out.text)) {
                lines += Line(
                    turn.key,
                    Who.DAN,
                    out.text,
                    at = out.writtenAt,
                    channel = PhoneBody.CHANNEL,
                    sending = if (turn.accepted) Sending.DONE else Sending.SENDING,
                    outgoing = out.id,
                )
            }
            lines += turn.items.filterNot { it.who == Who.KIT && turn.done && keptAlready(turn, it.text) }
            if (!turn.done) {
                doing = turn.doing ?: doing
                typing = typing || turn.current == null
            }
        }
        val sendingNow = turns.filter { !it.done }.mapNotNull { it.outgoing?.id }.toSet()
        for (out in outbox) {
            if (out.id in sendingNow) continue
            lines += Line(
                "o${out.id}",
                Who.DAN,
                out.text,
                at = out.writtenAt,
                channel = PhoneBody.CHANNEL,
                sending = if (out.failed != null) Sending.FAILED else Sending.WAITING,
                problem = out.failed ?: "",
                outgoing = out.id,
            )
        }
        _view.value = ChatView(lines, older && history.isNotEmpty(), loadingOlder, typing, doing)
    }

    private fun line(m: Message): Line = Line(
        "m${m.id}",
        if (m.fromDan) Who.DAN else if (m.role == "error") Who.ERROR else Who.KIT,
        m.text,
        detail = m.reply?.detail ?: "",
        at = m.at,
        channel = m.channel,
        cloud = m.source == "cloud",
    )

    /** Dan's message of a turn is in the history already (it was caught up mid-answer). */
    private fun savedAlready(turn: Turn, text: String): Boolean =
        history.tailMap(turn.baseId, false).values.any { it.fromDan && it.text.trim() == text.trim() }

    private fun keptAlready(turn: Turn, text: String): Boolean =
        history.tailMap(turn.baseId, false).values.any { !it.fromDan && it.text.trim() == text.trim() }

    /** Turns that are over and caught up give way to the history; their notes stay. */
    private fun settleTurns() {
        val over = turns.filter { it.done }
        val anchor = lastId()
        for (turn in over) {
            turn.items.filter { it.who == Who.NOTE || it.who == Who.ERROR }.forEach { notes += anchor to it }
        }
        turns.removeAll(over)
    }

    private fun add(turn: Turn, line: Line) {
        turn.items += line
        turn.current = null
        publish()
    }

    private fun replace(old: Outgoing, new: Outgoing) {
        val i = outbox.indexOfFirst { it.id == old.id }
        if (i >= 0) outbox[i] = new
        saveOutbox()
    }

    private fun lastId(): Long = if (history.isEmpty()) 0 else history.lastKey()

    /** The newest message Kit has kept, as far as the phone has seen. */
    val newestId: Long get() = lastId()

    private fun noteKey(): String = "n${noteCount++}-${newId()}"

    private fun now(): String = clock().toString()

    private fun save() {
        val keep = history.values.toList().takeLast(KEEP)
        store.write(HISTORY_FILE, KitJson.encodeToString(ListSerializer(Message.serializer()), keep))
    }

    private fun saveOutbox() {
        store.write(OUTBOX_FILE, KitJson.encodeToString(ListSerializer(Outgoing.serializer()), outbox.toList()))
    }

    companion object {
        const val HISTORY_FILE = "history.json"
        const val OUTBOX_FILE = "outbox.json"
        const val PAGE = 40
        const val CATCH_UP = 100
        const val MAX_CATCH_UP_PAGES = 5
        const val KEEP = 300

        /** A message that waited longer than this is sent with the time it was written. */
        const val WAITED_S = 30L
    }
}
