package io.github.senitage.kit

import android.content.Context
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.Data
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters

/**
 * One thing to do for Kit from outside the app: answer him from a notification, or
 * hush him from a notification or the Quick Settings tile.
 */
class ActWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val kit = (applicationContext as KitApp).kit
        if (!kit.paired.value) return Result.success()
        val ok = when (inputData.getString(WHAT)) {
            REPLY -> kit.replyFromNotification(inputData.getInt(ID, 0), inputData.getString(TEXT) ?: "")
            QUIET -> kit.quiet(inputData.getInt(MINUTES, 60))
            else -> true
        }
        return if (ok || runAttemptCount >= 3) Result.success() else Result.retry()
    }

    companion object {
        private const val WHAT = "what"
        private const val ID = "id"
        private const val TEXT = "text"
        private const val MINUTES = "minutes"
        private const val REPLY = "reply"
        private const val QUIET = "quiet"

        fun reply(context: Context, id: Int, text: String) =
            run(context, Data.Builder().putString(WHAT, REPLY).putInt(ID, id).putString(TEXT, text).build())

        /** Hush Kit for [minutes]; 0 lets him speak again. */
        fun quiet(context: Context, minutes: Int) =
            run(context, Data.Builder().putString(WHAT, QUIET).putInt(MINUTES, minutes).build())

        private fun run(context: Context, data: Data) {
            val request = OneTimeWorkRequestBuilder<ActWorker>()
                .setInputData(data)
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                .build()
            WorkManager.getInstance(context).enqueue(request)
        }
    }
}
