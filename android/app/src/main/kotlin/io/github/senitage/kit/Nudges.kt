package io.github.senitage.kit

import android.content.Context
import com.google.firebase.FirebaseApp
import com.google.firebase.FirebaseOptions
import com.google.firebase.messaging.FirebaseMessaging
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import io.github.senitage.kit.core.Nudge
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withTimeoutOrNull
import kotlin.coroutines.resume

/**
 * Kit's nudges: when he pipes up and the app is closed, his brain (kit.push) sends
 * a content-free push through Firebase, and the phone fetches what he said. Nothing
 * Kit says goes through Google. Firebase is set up here by hand from the build's
 * ids, so the repo needs no google-services file; without the ids there's no push
 * and CatchUpWorker looks for pipe-ups every half hour instead.
 */
object Nudges {
    /** Whether this build can get nudges at all. */
    val available: Boolean get() = BuildConfig.FIREBASE

    fun setUp(context: Context) {
        if (!available || FirebaseApp.getApps(context).isNotEmpty()) return
        val options = FirebaseOptions.Builder()
            .setProjectId(BuildConfig.FIREBASE_PROJECT_ID)
            .setApplicationId(BuildConfig.FIREBASE_APP_ID)
            .setApiKey(BuildConfig.FIREBASE_API_KEY)
            .setGcmSenderId(BuildConfig.FIREBASE_SENDER_ID)
            .build()
        runCatching { FirebaseApp.initializeApp(context, options) }
    }

    /** This phone's push token, for Kit to nudge it with; null without Firebase or offline. */
    suspend fun token(): String? {
        if (!available) return null
        return runCatching {
            suspendCancellableCoroutine<String?> { cont ->
                FirebaseMessaging.getInstance().token.addOnCompleteListener { task ->
                    cont.resume(if (task.isSuccessful) task.result else null)
                }
            }
        }.getOrNull()
    }
}

/** Hears Kit's nudges, and tells him when the phone's token changes. */
class KitMessagingService : FirebaseMessagingService() {
    private val kit: Kit get() = (application as KitApp).kit

    override fun onNewToken(token: String) {
        kit.pushTokenChanged()
    }

    override fun onMessageReceived(message: RemoteMessage) {
        val nudge = Nudge.from(message.data) ?: return
        // A high-priority push gives the app a few seconds of network: use them now,
        // and leave it to a worker if Kit didn't answer in time.
        val done = runBlocking { withTimeoutOrNull(8_000) { kit.catchUp(test = !nudge.pipeUp) } }
        if (done != true) CatchUpWorker.now(this)
    }
}
