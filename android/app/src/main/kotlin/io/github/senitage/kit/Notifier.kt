package io.github.senitage.kit

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.app.Person
import androidx.core.app.RemoteInput
import androidx.core.content.ContextCompat
import io.github.senitage.kit.core.Message
import java.time.OffsetDateTime

/**
 * Kit's notifications: a pipe-up while the app is closed, shown as a message from
 * him you can answer from the notification, with a button to hush him for an hour.
 */
object Notifier {
    const val CHANNEL_PIPE_UPS = "pipe_ups"
    const val CHANNEL_OTHER = "other"
    const val REPLY_KEY = "reply"
    const val EXTRA_ID = "id"
    const val EXTRA_SAID = "said"
    const val ACTION_REPLY = "io.github.senitage.kit.REPLY"
    const val ACTION_QUIET = "io.github.senitage.kit.QUIET"
    private const val TEST_ID = 1
    private const val GROUP = "kit"

    fun makeChannels(context: Context) {
        val manager = context.getSystemService(NotificationManager::class.java) ?: return
        manager.createNotificationChannel(
            NotificationChannel(CHANNEL_PIPE_UPS, "Kit speaking up", NotificationManager.IMPORTANCE_HIGH).apply {
                description = "When Kit says something of his own accord and the app is closed."
            },
        )
        manager.createNotificationChannel(
            NotificationChannel(CHANNEL_OTHER, "Other", NotificationManager.IMPORTANCE_LOW).apply {
                description = "Test nudges and the like."
            },
        )
    }

    /** Whether the phone lets Kit's notifications through at all. */
    fun allowed(context: Context): Boolean {
        if (Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            return false
        }
        return NotificationManagerCompat.from(context).areNotificationsEnabled()
    }

    /** A pipe-up, as a message from Kit with Reply and Quiet. */
    fun pipeUp(context: Context, message: Message, name: String) {
        if (!allowed(context)) return
        val id = message.id.toInt()
        val style = NotificationCompat.MessagingStyle(me())
            .addMessage(message.text, atMillis(message.at), kit(name))
        post(context, id, build(context, id, name, style).build())
    }

    /** After an answer from the notification: what Dan said and what Kit said back. */
    fun answered(context: Context, id: Int, name: String, said: String, answer: String?) {
        if (!allowed(context)) return
        val now = System.currentTimeMillis()
        val style = NotificationCompat.MessagingStyle(me()).addMessage(said, now, me())
        if (answer != null) style.addMessage(answer, now, kit(name))
        val built = build(context, id, name, style)
        if (answer == null) built.setSubText("waiting to reach $name")
        post(context, id, built.build())
    }

    /** `kit nudge` on the PC: shows the nudge got through. */
    fun test(context: Context, name: String) {
        if (!allowed(context)) return
        val built = NotificationCompat.Builder(context, CHANNEL_OTHER)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle("$name can reach this phone")
            .setContentText("A test nudge from Kit's PC got through.")
            .setContentIntent(open(context))
            .setAutoCancel(true)
        post(context, TEST_ID, built.build())
    }

    fun clear(context: Context) {
        NotificationManagerCompat.from(context).cancelAll()
    }

    private fun build(context: Context, id: Int, name: String, style: NotificationCompat.MessagingStyle): NotificationCompat.Builder {
        val reply = NotificationCompat.Action.Builder(0, "Reply", replyIntent(context, id))
            .addRemoteInput(RemoteInput.Builder(REPLY_KEY).setLabel("Say something to $name").build())
            .setAllowGeneratedReplies(false)
            .build()
        val quiet = NotificationCompat.Action.Builder(0, "Quiet for an hour", quietIntent(context)).build()
        return NotificationCompat.Builder(context, CHANNEL_PIPE_UPS)
            .setSmallIcon(R.drawable.ic_notification)
            .setStyle(style)
            .setContentIntent(open(context))
            .setCategory(NotificationCompat.CATEGORY_MESSAGE)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setGroup(GROUP)
            .setAutoCancel(true)
            .setOnlyAlertOnce(true)
            .addAction(reply)
            .addAction(quiet)
    }

    private fun post(context: Context, id: Int, notification: android.app.Notification) {
        runCatching { NotificationManagerCompat.from(context).notify(id, notification) }
    }

    private fun me() = Person.Builder().setName("You").build()

    private fun kit(name: String) = Person.Builder().setName(name).setKey("kit").setImportant(true).build()

    private fun atMillis(at: String): Long =
        runCatching { OffsetDateTime.parse(at).toInstant().toEpochMilli() }.getOrDefault(System.currentTimeMillis())

    private fun open(context: Context): PendingIntent {
        val intent = Intent(context, MainActivity::class.java).setAction(MainActivity.ACTION_OPEN)
        return PendingIntent.getActivity(context, 0, intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
    }

    private fun replyIntent(context: Context, id: Int): PendingIntent {
        val intent = Intent(context, ReplyReceiver::class.java).setAction(ACTION_REPLY).putExtra(EXTRA_ID, id)
        // Mutable, so the system can put the typed reply in it.
        return PendingIntent.getBroadcast(context, id, intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_MUTABLE)
    }

    private fun quietIntent(context: Context): PendingIntent {
        val intent = Intent(context, ReplyReceiver::class.java).setAction(ACTION_QUIET)
        return PendingIntent.getBroadcast(context, 0, intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
    }
}

/** The notification's buttons: Reply (with what was typed) and Quiet for an hour. */
class ReplyReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val kit = (context.applicationContext as KitApp).kit
        when (intent.action) {
            Notifier.ACTION_REPLY -> {
                val said = RemoteInput.getResultsFromIntent(intent)?.getCharSequence(Notifier.REPLY_KEY)?.toString()?.trim()
                val id = intent.getIntExtra(Notifier.EXTRA_ID, 0)
                if (said.isNullOrEmpty()) return
                Notifier.answered(context, id, kit.name, said, null)
                ActWorker.reply(context, id, said)
            }
            Notifier.ACTION_QUIET -> {
                Notifier.clear(context)
                ActWorker.quiet(context, 60)
            }
        }
    }
}
