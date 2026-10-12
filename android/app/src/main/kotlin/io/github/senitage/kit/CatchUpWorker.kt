package io.github.senitage.kit

import android.content.Context
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import java.util.concurrent.TimeUnit

/**
 * Looks in on Kit with the app closed: pipe-ups Dan hasn't seen become
 * notifications, the phone tells Kit how it is (home or out, battery), and the
 * widget is redrawn. Runs every half hour, after a nudge the push didn't finish,
 * and when the battery or charger changes (SensesReceiver).
 */
class CatchUpWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val kit = (applicationContext as KitApp).kit
        if (!kit.paired.value) return Result.success()
        val ok = kit.catchUp()
        return if (ok || runAttemptCount >= 2) Result.success() else Result.retry()
    }

    companion object {
        private const val EVERY = "kit-catch-up"
        private const val NOW = "kit-catch-up-now"

        /** Every half hour, kept across restarts; the no-Firebase way to hear pipe-ups. */
        fun schedule(context: Context) {
            val request = PeriodicWorkRequestBuilder<CatchUpWorker>(30, TimeUnit.MINUTES)
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                .build()
            WorkManager.getInstance(context).enqueueUniquePeriodicWork(EVERY, ExistingPeriodicWorkPolicy.KEEP, request)
        }

        /** As soon as there's a network. */
        fun now(context: Context) {
            val request = OneTimeWorkRequestBuilder<CatchUpWorker>()
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                .build()
            WorkManager.getInstance(context).enqueueUniqueWork(NOW, ExistingWorkPolicy.APPEND_OR_REPLACE, request)
        }
    }
}
