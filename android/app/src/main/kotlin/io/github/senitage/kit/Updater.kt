package io.github.senitage.kit

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.Settings
import androidx.core.content.FileProvider
import io.github.senitage.kit.core.Updates
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.util.concurrent.TimeUnit

/**
 * Updates the app from the Kit repo's GitHub Releases, like the desk app: GitHub
 * builds each version, the app finds a newer one, downloads it and hands it to
 * Android to install (allowed once, under "Install unknown apps").
 */
class Updater(private val context: Context) {
    private val http = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .build()

    /** A newer version than this one, or null. Throws when GitHub can't be reached. */
    suspend fun check(): Updates.Release? = withContext(Dispatchers.IO) {
        val request = Request.Builder()
            .url(Updates.releasesUrl(BuildConfig.REPO))
            .header("Accept", "application/vnd.github+json")
            .build()
        http.newCall(request).execute().use { response ->
            if (!response.isSuccessful) throw IllegalStateException("GitHub answered ${response.code}")
            val releases = Updates.parse(response.body?.string() ?: "[]")
            Updates.newest(releases, BuildConfig.VERSION_CODE, tests = BuildConfig.TEST_BUILD)
        }
    }

    /** Download [release]'s APK; returns the file. */
    suspend fun download(release: Updates.Release, progress: (Float) -> Unit = {}): File = withContext(Dispatchers.IO) {
        val asset = release.apk ?: throw IllegalStateException("that release has no app in it")
        val folder = File(context.cacheDir, "updates").apply { mkdirs() }
        folder.listFiles()?.forEach { it.delete() }
        val file = File(folder, asset.name.ifBlank { "kit.apk" })
        http.newCall(Request.Builder().url(asset.url).build()).execute().use { response ->
            if (!response.isSuccessful) throw IllegalStateException("GitHub answered ${response.code}")
            val body = response.body ?: throw IllegalStateException("nothing came")
            val total = body.contentLength().takeIf { it > 0 } ?: asset.size
            body.byteStream().use { input ->
                file.outputStream().use { output ->
                    val buffer = ByteArray(64 * 1024)
                    var done = 0L
                    while (true) {
                        val n = input.read(buffer)
                        if (n < 0) break
                        output.write(buffer, 0, n)
                        done += n
                        if (total > 0) progress(done.toFloat() / total)
                    }
                }
            }
        }
        file
    }

    /** Whether Android lets Kit install updates; if not, [allow] opens the switch. */
    fun canInstall(): Boolean = context.packageManager.canRequestPackageInstalls()

    fun allow() {
        val intent = Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:${context.packageName}"))
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        context.startActivity(intent)
    }

    fun install(file: File) {
        val uri = FileProvider.getUriForFile(context, "${context.packageName}.files", file)
        val intent = Intent(Intent.ACTION_VIEW)
            .setDataAndType(uri, "application/vnd.android.package-archive")
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
        context.startActivity(intent)
    }
}
