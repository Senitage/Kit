package io.github.senitage.kit

import android.app.Application
import android.content.BroadcastReceiver
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.Build
import android.os.PowerManager
import android.os.SystemClock
import android.service.quicksettings.TileService
import androidx.core.content.ContextCompat
import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.ProcessLifecycleOwner
import io.github.senitage.kit.core.Character
import io.github.senitage.kit.core.ChatEvent
import io.github.senitage.kit.core.Conversation
import io.github.senitage.kit.core.DeviceName
import io.github.senitage.kit.core.Director
import io.github.senitage.kit.core.Face
import io.github.senitage.kit.core.Hello
import io.github.senitage.kit.core.HelloAnswer
import io.github.senitage.kit.core.KitAddress
import io.github.senitage.kit.core.KitClient
import io.github.senitage.kit.core.KitError
import io.github.senitage.kit.core.LifeState
import io.github.senitage.kit.core.PairingLink
import io.github.senitage.kit.core.PhoneBody
import io.github.senitage.kit.core.Reach
import io.github.senitage.kit.core.Updates
import io.github.senitage.kit.core.Watcher
import io.github.senitage.kit.core.newPipeUps
import io.github.senitage.kit.core.seenUpTo
import io.github.senitage.kit.widget.KitWidget
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.MainScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File

/** How Kit's face is drawn at the top: his 3D face when Kit has one, or always 2D. */
enum class FaceMode { AUTO, FLAT }

/** The app's pages, along the bottom. */
enum class Tab { CHAT, KIT, MEMORY, SETTINGS }

/** Where an app update has got to. */
sealed interface UpdateState {
    data object None : UpdateState

    data class Ready(val release: Updates.Release) : UpdateState

    data class Downloading(val progress: Float) : UpdateState

    data class Failed(val why: String) : UpdateState
}

/**
 * The app's side of Kit: who Kit is and how to reach him, the conversation, his
 * face, and keeping an eye on him while the app is open. One per app (KitApp).
 */
class Kit(private val app: Application) {
    val scope = MainScope()
    private val prefs = app.getSharedPreferences("kit", Context.MODE_PRIVATE)
    private val store = FileStore(File(app.filesDir, "kit"))
    private val updater = Updater(app)

    val conversation = Conversation(scope, store)
    val senses = PhoneSenses(app, prefs) { conversation.client }
    private val shaker = Shaker(app) { director.shaken() }
    val watcher = Watcher(scope) { Net.vpnUp(app) }
    val face = Face(loadCharacter())
    val director = Director(scope, face, { SystemClock.elapsedRealtime() / 1000.0 })

    private val _paired = MutableStateFlow(false)
    val paired: StateFlow<Boolean> = _paired.asStateFlow()

    private val _hello = MutableStateFlow<HelloAnswer?>(null)
    val hello: StateFlow<HelloAnswer?> = _hello.asStateFlow()

    private val _life = MutableStateFlow<LifeState?>(null)
    val life: StateFlow<LifeState?> = _life.asStateFlow()

    private val _faceMode = MutableStateFlow(FaceMode.valueOf(prefs.getString(FACE_MODE, FaceMode.AUTO.name) ?: FaceMode.AUTO.name))
    val faceMode: StateFlow<FaceMode> = _faceMode.asStateFlow()

    private val _update = MutableStateFlow<UpdateState>(UpdateState.None)
    val update: StateFlow<UpdateState> = _update.asStateFlow()

    private val _lowPower = MutableStateFlow(false)

    /** Battery saver is on: his face stays 2D to spare it. */
    val lowPower: StateFlow<Boolean> = _lowPower.asStateFlow()

    private val _nudges = MutableStateFlow<Boolean?>(null)

    /** Whether Kit said he can nudge this phone (null until he's been asked). */
    val nudges: StateFlow<Boolean?> = _nudges.asStateFlow()

    private val _quietUntil = MutableStateFlow(prefs.getString(QUIET_UNTIL, null))

    /** When he's been told to keep quiet until, as Kit gives it, or null. */
    val quietUntil: StateFlow<String?> = _quietUntil.asStateFlow()

    val reach: StateFlow<Reach> get() = watcher.reach

    /** The page showing. */
    val tab = MutableStateFlow(Tab.CHAT)

    /** Words to put in the chat box: text shared to Kit from another app. */
    val draft = MutableStateFlow<String?>(null)

    /** The link the app was opened with (a `kit pair` QR code), waiting to be used. */
    val pairingLink = MutableStateFlow<PairingLink?>(null)

    /** Kit's name, as he gave it, for notifications. */
    val name: String get() = _hello.value?.name ?: prefs.getString(KIT_NAME, "Kit") ?: "Kit"

    /** The newest message this phone has shown; pipe-ups after it get notifications. */
    private var lastSeen: Long
        get() = prefs.getLong(LAST_SEEN, 0)
        set(value) = prefs.edit().putLong(LAST_SEEN, value).apply()

    var askedForNotifications: Boolean
        get() = prefs.getBoolean(ASKED_NOTIFY, false)
        set(value) = prefs.edit().putBoolean(ASKED_NOTIFY, value).apply()

    var address: String
        get() = prefs.getString(ADDRESS, "") ?: ""
        private set(value) = prefs.edit().putString(ADDRESS, value).apply()

    var deviceName: String
        get() = prefs.getString(NAME, PhoneBody.KIND) ?: PhoneBody.KIND
        private set(value) = prefs.edit().putString(NAME, value).apply()

    private var foreground = false
    private var stopWatchingNet: () -> Unit = {}
    private var powerReceiver: BroadcastReceiver? = null
    private var widgetDrawnFor: String? = null

    init {
        conversation.cues = director
        conversation.trouble = { watcher.trouble(it) }
        conversation.load()
        watcher.onOnline = { online() }
        watcher.onLife = { life ->
            _life.value = life
            director.start(life)
            tookIn(life)
        }
        watcher.onEvent = { event ->
            if (event.type == "pipe_up") {
                event.reply?.let { conversation.pipeUp(it) }
            } else {
                director.life(event)
                if (event.type == "mood") refreshLife()
            }
        }
        scope.launch {
            watcher.reach.collect { reach ->
                val online = reach == Reach.Online
                conversation.setOnline(online)
                director.setOnline(online || reach == Reach.Checking)
            }
        }
        connect()
        ProcessLifecycleOwner.get().lifecycle.addObserver(object : DefaultLifecycleObserver {
            override fun onStart(owner: LifecycleOwner) = cameForward()

            override fun onStop(owner: LifecycleOwner) = wentAway()
        })
    }

    // ---- pairing ----

    /**
     * Pair from what was typed in: Kit's address and his own token, swapped for one
     * of this phone's own. Returns a problem in words, or null when it worked.
     */
    suspend fun pair(typedAddress: String, kitToken: String, typedName: String): String? {
        val url = KitAddress.normalize(typedAddress)
            ?: return "That doesn't look like an address. Try Kit's Tailscale address or name, like kit-server."
        val token = kitToken.trim()
        if (token.isEmpty()) return "Paste Kit's token. It's on the desk app's This PC page, under Copy."
        val name = DeviceName.tidy(typedName.ifBlank { PhoneBody.KIND })
        val client = KitClient(url, token)
        return try {
            client.health()
            val answer = client.pair(name)
            use(url, name, answer.token)
            null
        } catch (e: KitError.Unreachable) {
            if (Net.vpnUp(app)) {
                "Can't reach Kit at $url. Is his PC on, and is that the right address?"
            } else {
                "Can't reach Kit at $url. Tailscale looks off on this phone: turn it on and try again."
            }
        } catch (e: KitError.BadToken) {
            "Kit didn't accept that token. Copy it again from the desk app's This PC page."
        } catch (e: KitError.NotAllowed) {
            "That's another device's token. Pairing needs Kit's own token, from the desk app's This PC page."
        } catch (e: KitError) {
            e.message ?: "Kit couldn't pair this phone."
        }
    }

    /** Pair from a `kit pair` QR code: it already holds this phone's own token. */
    suspend fun pair(link: PairingLink): String? {
        val client = KitClient(link.url, link.token)
        return try {
            client.health()
            client.hello(Hello(id = link.name, name = Build.MODEL ?: "Phone", app = BuildConfig.VERSION_NAME))
            use(link.url, link.name, link.token)
            null
        } catch (e: KitError.Unreachable) {
            "Can't reach Kit at ${link.url}. Is Tailscale on?"
        } catch (e: KitError.BadToken) {
            "That code is out of date. Run kit pair again on Kit's PC."
        } catch (e: KitError) {
            e.message ?: "Kit couldn't pair this phone."
        }
    }

    /** Forget Kit on this phone, and tell Kit to forget this phone's token. */
    suspend fun unpair() {
        val client = conversation.client
        runCatching { client?.unregisterPush(deviceName) }
        runCatching { client?.unpair(deviceName) }
        _nudges.value = null
        prefs.edit().remove(TOKEN).apply()
        watcher.stop()
        watcher.client = null
        conversation.client = null
        _hello.value = null
        _paired.value = false
    }

    private fun use(url: String, name: String, token: String) {
        address = url
        deviceName = name
        prefs.edit().putString(TOKEN, Secrets.seal(token)).apply()
        connect()
        if (foreground) watcher.recheck()
    }

    private fun connect() {
        val token = prefs.getString(TOKEN, null)?.let { Secrets.open(it) }
        if (token == null || address.isEmpty()) {
            _paired.value = false
            return
        }
        val client = KitClient(address, token)
        conversation.client = client
        conversation.body = deviceName
        watcher.client = client
        _paired.value = true
    }

    // ---- while the app is open ----

    private fun cameForward() {
        foreground = true
        stopWatchingNet = Net.watch(app) {
            scope.launch {
                watcher.recheck()
                senses.report()
            }
        }
        if (_paired.value) watcher.start()
        Notifier.clear(app)
        shaker.start()
        watchPower()
        checkForUpdate()
        scope.launch { senses.report() }
    }

    private fun wentAway() {
        foreground = false
        stopWatchingNet()
        watcher.stop()
        shaker.stop()
        stopWatchingPower()
        lastSeen = maxOf(lastSeen, conversation.newestId)
        if (conversation.waiting > 0) SendWorker.schedule(app)
        scope.launch { drawWidget() }
    }

    private fun watchPower() {
        val pm = app.getSystemService(PowerManager::class.java)
        _lowPower.value = pm?.isPowerSaveMode == true
        val receiver = object : BroadcastReceiver() {
            override fun onReceive(context: Context, intent: Intent) {
                _lowPower.value = pm?.isPowerSaveMode == true
            }
        }
        ContextCompat.registerReceiver(
            app,
            receiver,
            IntentFilter(PowerManager.ACTION_POWER_SAVE_MODE_CHANGED),
            ContextCompat.RECEIVER_NOT_EXPORTED,
        )
        powerReceiver = receiver
    }

    private fun stopWatchingPower() {
        powerReceiver?.let { runCatching { app.unregisterReceiver(it) } }
        powerReceiver = null
    }

    private suspend fun online() {
        val client = conversation.client ?: return
        try {
            val answer = client.hello(Hello(id = deviceName, name = Build.MODEL ?: "Phone", app = BuildConfig.VERSION_NAME))
            _hello.value = answer
            prefs.edit().putString(KIT_NAME, answer.name).apply()
            val sheet = client.face()
            store.write(SHEET_FILE, sheet.toString())
            face.character = Character(sheet)
            face.setEmotion(face.emotion, SystemClock.elapsedRealtime() / 1000.0)
        } catch (e: KitError) {
            watcher.trouble(e)
        }
        conversation.refresh()
        lastSeen = maxOf(lastSeen, conversation.newestId)
        scope.launch { registerPush() }
    }

    fun refreshLife() {
        val client = conversation.client ?: return
        scope.launch { runCatching { _life.value = client.life() } }
    }

    /** From the background: send what waited. True when nothing is left. */
    suspend fun sendWaiting(): Boolean = conversation.sendWaiting()

    fun setFaceMode(mode: FaceMode) {
        _faceMode.value = mode
        prefs.edit().putString(FACE_MODE, mode.name).apply()
    }

    /** The 3D face page's address, when the face should be 3D. */
    fun facePage(): String? {
        val hello = _hello.value ?: return null
        if (_faceMode.value == FaceMode.FLAT || _lowPower.value || hello.face.style != "model") return null
        return conversation.client?.facePage(hello.face.page)
    }

    private fun tookIn(life: LifeState) {
        _quietUntil.value = life.snoozedUntil
        prefs.edit().putString(QUIET_UNTIL, life.snoozedUntil).apply()
        TileService.requestListeningState(app, ComponentName(app, QuietTile::class.java))
    }

    // ---- with the app closed ----

    /**
     * Look in on Kit: pipe-ups Dan hasn't seen become notifications (unless the
     * app's open, where the chat shows them), the phone reports how it is, and the
     * widget is redrawn. [test] for a test nudge from `kit nudge`. True when Kit
     * answered.
     */
    suspend fun catchUp(test: Boolean = false): Boolean {
        val client = conversation.client ?: return true
        var ok = true
        try {
            val messages = client.messages(50, after = lastSeen)
            if (!foreground && senses.senses.value.notify) {
                for (m in newPipeUps(messages, lastSeen)) Notifier.pipeUp(app, m, name)
            }
            if (!foreground) lastSeen = seenUpTo(messages, lastSeen)
            if (test) Notifier.test(app, name)
            runCatching { client.life() }.getOrNull()?.let {
                _life.value = it
                tookIn(it)
            }
        } catch (e: KitError) {
            ok = false
        }
        ok = senses.report() && ok
        drawWidget()
        return ok
    }

    /** Answer Kit from a notification: his reply goes back into it. True when it got through. */
    suspend fun replyFromNotification(id: Int, said: String): Boolean {
        val client = conversation.client ?: return true
        return try {
            var answer: String? = null
            client.chat(said, body = deviceName).collect { event ->
                if (event is ChatEvent.Done) answer = event.reply.text
                if (event is ChatEvent.Error) throw KitError.Server(500, event.message)
            }
            Notifier.answered(app, id, name, said, answer ?: "...")
            if (foreground) conversation.refresh()
            true
        } catch (e: KitError) {
            // Kit's out of reach: it waits in the chat's outbox and goes when he's back.
            withContext(Dispatchers.Main) { conversation.send(said) }
            SendWorker.schedule(app)
            Notifier.answered(app, id, name, said, null)
            false
        }
    }

    /** Keep him from piping up for [minutes] (0 lets him again). True when Kit took it. */
    suspend fun quiet(minutes: Int): Boolean {
        val client = conversation.client ?: return true
        return try {
            val life = client.snooze(minutes)
            _life.value = life
            tookIn(life)
            true
        } catch (e: KitError) {
            false
        }
    }

    // ---- nudges ----

    /** Tell Kit this phone's push token, so he can nudge it. */
    suspend fun registerPush() {
        val client = conversation.client ?: return
        if (!senses.senses.value.notify) return
        val token = Nudges.token()
        if (token == null) {
            if (Nudges.available) return
            _nudges.value = false
            return
        }
        runCatching { _nudges.value = client.registerPush(deviceName, "fcm", token) }
    }

    suspend fun stopPush() {
        runCatching { conversation.client?.unregisterPush(deviceName) }
        _nudges.value = false
    }

    fun pushTokenChanged() {
        scope.launch { registerPush() }
    }

    /** The notifications switch on the Settings page. */
    fun setNotify(on: Boolean) {
        senses.set(senses.senses.value.copy(notify = on))
        scope.launch { if (on) registerPush() else stopPush() }
    }

    // ---- the widget ----

    private suspend fun drawWidget() {
        val life = _life.value
        val key = "${life?.face}|${life?.mood}|${conversation.newestId}|${_quietUntil.value}"
        if (key == widgetDrawnFor) return
        widgetDrawnFor = key
        runCatching { KitWidget.refresh(app) }
    }

    private fun loadCharacter(): Character {
        val saved = store.read(SHEET_FILE)
        if (saved != null) runCatching { return Character.parse(saved) }
        return Character.parse(app.assets.open("kit2d.json").bufferedReader().use { it.readText() })
    }

    // ---- updates ----

    fun checkForUpdate(force: Boolean = false) {
        val last = prefs.getLong(CHECKED_AT, 0)
        if (!force && System.currentTimeMillis() - last < UPDATE_EVERY_MS) return
        scope.launch {
            try {
                val release = updater.check()
                prefs.edit().putLong(CHECKED_AT, System.currentTimeMillis()).apply()
                _update.value = if (release != null) UpdateState.Ready(release) else UpdateState.None
                if (release == null && force) conversation.note("Kit for Android ${BuildConfig.VERSION_NAME} is the newest.")
            } catch (e: Exception) {
                if (force) _update.value = UpdateState.Failed("Couldn't check GitHub for a new version.")
            }
        }
    }

    fun installUpdate() {
        val ready = _update.value as? UpdateState.Ready ?: return
        if (!updater.canInstall()) {
            updater.allow()
            return
        }
        scope.launch {
            try {
                val file = updater.download(ready.release) { _update.value = UpdateState.Downloading(it) }
                _update.value = UpdateState.Ready(ready.release)
                updater.install(file)
            } catch (e: Exception) {
                _update.value = UpdateState.Failed("The download didn't finish. Try again on Wi-Fi.")
            }
        }
    }

    fun dismissUpdate() {
        _update.value = UpdateState.None
    }

    companion object {
        private const val ADDRESS = "address"
        private const val NAME = "device_name"
        private const val TOKEN = "token_sealed"
        private const val FACE_MODE = "face_mode"
        private const val CHECKED_AT = "update_checked_at"
        private const val SHEET_FILE = "character.json"
        private const val KIT_NAME = "kit_name"
        private const val LAST_SEEN = "last_seen"
        private const val ASKED_NOTIFY = "asked_notify"
        private const val QUIET_UNTIL = "quiet_until"
        private const val UPDATE_EVERY_MS = 6 * 60 * 60 * 1000L
    }
}
