package io.github.senitage.kit.core

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/** Whether Kit can be reached, and if not, why, in words. */
sealed interface Reach {
    data object Checking : Reach

    data object Online : Reach

    /** Nothing answered. [vpnOff] when the phone's VPN (Tailscale) isn't on. */
    data class Away(val vpnOff: Boolean) : Reach

    /** Kit answered but doesn't know this phone any more. */
    data object Unpaired : Reach

    /** Kit answered with something odd. */
    data class Trouble(val detail: String) : Reach
}

/** The banner for each [Reach], in plain words. */
fun Reach.words(name: String = "Kit"): String = when (this) {
    Reach.Checking -> "Looking for $name..."
    Reach.Online -> ""
    is Reach.Away ->
        if (vpnOff) {
            "Can't reach $name. Tailscale is off on this phone."
        } else {
            "Can't reach $name. His PC may be off or asleep. Messages wait and send when he's back."
        }
    Reach.Unpaired -> "$name doesn't know this phone any more. Pair it again."
    is Reach.Trouble -> "$name answered oddly: $detail"
}

/**
 * Keeps an eye on Kit while the app is open: checks he's there, then listens to his
 * life events (`/api/life/events`, a long poll), and checks again after trouble,
 * sooner at first and then less often.
 */
class Watcher(
    private val scope: CoroutineScope,
    private val vpnUp: () -> Boolean = { true },
) {
    var client: KitClient? = null

    /** Kit's back: say hello, refresh, send what waited. */
    var onOnline: suspend () -> Unit = {}

    var onEvent: suspend (LifeEvent) -> Unit = {}

    /** The brain restarted or the app just started: how he is now. */
    var onLife: suspend (LifeState) -> Unit = {}

    private val _reach = MutableStateFlow<Reach>(Reach.Checking)
    val reach: StateFlow<Reach> = _reach.asStateFlow()

    private var job: Job? = null

    fun start() {
        if (job?.isActive == true) return
        job = scope.launch { run() }
    }

    fun stop() {
        job?.cancel()
        job = null
    }

    /** Look again now (after a failed send, or when the network changes). */
    fun recheck() {
        stop()
        start()
    }

    /** A call elsewhere found Kit out of reach, or the token refused. */
    fun trouble(e: KitError) {
        when (e) {
            is KitError.BadToken -> _reach.value = Reach.Unpaired
            is KitError.Unreachable -> if (_reach.value == Reach.Online) recheck()
            else -> Unit
        }
    }

    private suspend fun run() {
        var failures = 0
        while (currentCoroutineContext().isActive) {
            val c = client ?: return
            try {
                c.health()
                val life = c.life()
                _reach.value = Reach.Online
                failures = 0
                onOnline()
                onLife(life)
                listen(c, life.lastEvent)
            } catch (e: CancellationException) {
                throw e
            } catch (e: KitError.BadToken) {
                _reach.value = Reach.Unpaired
                return
            } catch (e: KitError.Unreachable) {
                _reach.value = Reach.Away(vpnOff = !vpnUp())
            } catch (e: KitError) {
                _reach.value = Reach.Trouble(e.message ?: "")
            }
            failures++
            delay(RETRY_MS[minOf(failures, RETRY_MS.size) - 1])
        }
    }

    /** Life events until something goes wrong; a restarted brain starts over. */
    private suspend fun listen(c: KitClient, from: Long) {
        var after = from
        while (currentCoroutineContext().isActive) {
            val got = c.lifeEvents(after)
            if (got.last < after) { // the brain restarted: its event ids began again
                onLife(c.life())
                after = got.last
                continue
            }
            for (raw in got.events) {
                val event = LifeEvent.from(raw)
                onEvent(event)
                after = maxOf(after, event.id)
            }
        }
    }

    companion object {
        private val RETRY_MS = longArrayOf(2_000, 5_000, 10_000, 20_000, 30_000)
    }
}
