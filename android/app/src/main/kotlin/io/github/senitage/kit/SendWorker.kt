package io.github.senitage.kit

import android.content.Context
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * Sends the messages that waited, with the app closed: Android runs this once
 * there's a network, and again later if Kit still can't be reached.
 */
class SendWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val kit = (applicationContext as KitApp).kit
        if (!kit.paired.value) return Result.success()
        val done = withContext(Dispatchers.Main) { kit.sendWaiting() }
        return if (done) Result.success() else Result.retry()
    }

    companion object {
        private const val NAME = "kit-send-waiting"

        fun schedule(context: Context) {
            val request = OneTimeWorkRequestBuilder<SendWorker>()
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                .build()
            WorkManager.getInstance(context).enqueueUniqueWork(NAME, ExistingWorkPolicy.REPLACE, request)
        }
    }
}
