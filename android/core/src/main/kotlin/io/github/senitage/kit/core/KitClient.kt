package io.github.senitage.kit.core

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import okhttp3.Call
import okhttp3.Callback
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import java.io.IOException
import java.time.OffsetDateTime
import java.time.format.DateTimeFormatter
import java.util.concurrent.TimeUnit
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

/** Why a call to Kit didn't work, in a form the app can explain. */
sealed class KitError(message: String, cause: Throwable? = null) : Exception(message, cause) {
    /** Nothing answered: Tailscale is off, Kit's PC is off, or the address is wrong. */
    class Unreachable(cause: Throwable?) : KitError("Can't reach Kit", cause)

    /** Kit answered, but not to this token (unpaired, or paired again elsewhere). */
    class BadToken : KitError("Kit doesn't know this phone's token")

    /** Only Kit's own token can do that (pairing). */
    class NotAllowed(detail: String) : KitError(detail)

    /** Kit answered with an error. */
    class Server(val code: Int, detail: String) : KitError(detail)

    /** The answer started and then the line dropped: the message did get there. */
    class Broken(cause: Throwable?) : KitError("The line dropped mid-answer", cause)
}

/**
 * Talks to Kit's brain over HTTP (docs/5 Reference/API.md). [baseUrl] is from
 * [KitAddress.normalize]; [token] is this phone's own token from pairing (or Kit's
 * shared token, only while pairing).
 */
class KitClient(
    val baseUrl: String,
    private val token: String,
    http: OkHttpClient = defaultHttp(),
) {
    private val http = http
    private val longHttp = http.newBuilder().readTimeout(LONG_READ_S, TimeUnit.SECONDS).build()
    private val base: HttpUrl = baseUrl.toHttpUrlOrNull() ?: throw IllegalArgumentException("not an address: $baseUrl")

    suspend fun health(): Health = decode(call(get("/api/health", auth = false)))

    /** Swap Kit's own token (the one this client has) for a token of the phone's own. */
    suspend fun pair(name: String, kind: String = PhoneBody.KIND): PairAnswer {
        val body = buildJsonObject {
            put("name", name)
            put("kind", kind)
        }
        return decode(call(post("/api/devices/pair", body.toString())))
    }

    suspend fun unpair(name: String) {
        call(request(url("/api/devices/$name")).delete().build())
    }

    suspend fun hello(hello: Hello): HelloAnswer =
        decode(call(post("/api/bodies/hello", KitJson.encodeToString(hello))))

    /**
     * Messages, oldest first: the latest [limit] across the whole history when
     * [before] and [after] are null; else the page just before or after a message id.
     */
    suspend fun messages(limit: Int = 50, before: Long? = null, after: Long? = null): List<Message> {
        val url = url("/api/messages").newBuilder().addQueryParameter("limit", limit.toString())
        when {
            after != null -> url.addQueryParameter("after", after.toString())
            else -> url.addQueryParameter("before", (before ?: LATEST).toString())
        }
        return decode(call(request(url.build()).get().build()))
    }

    suspend fun newChat() {
        call(post("/api/chat/new", "{}"))
    }

    suspend fun life(): LifeState = decode(call(get("/api/life")))

    /** Life events after [after], waiting up to [wait] seconds for one. */
    suspend fun lifeEvents(after: Long, wait: Int = 25): LifeEvents {
        val url = url("/api/life/events").newBuilder()
            .addQueryParameter("after", after.toString())
            .addQueryParameter("wait", wait.toString())
            .build()
        return decode(call(request(url).get().build(), longHttp))
    }

    /** The character sheet Kit is set to (for drawing him in 2D). */
    suspend fun face(): JsonObject = decode(call(get("/api/face")))

    /** The 3D face page for this body, from the hello's answer. */
    fun facePage(page: String): String = base.resolve(page)?.toString() ?: "$baseUrl/face/?app=phone"

    /**
     * Send a message and stream his answer. The first event is [ChatEvent.Accepted]
     * once the brain has the message. Before that, a failure is [KitError.Unreachable]
     * (send it again later); after it, [KitError.Broken] (it got there, don't resend).
     */
    fun chat(
        text: String,
        channel: String = PhoneBody.CHANNEL,
        body: String = "",
        sentAt: OffsetDateTime? = null,
        spoken: Boolean = false,
    ): Flow<ChatEvent> = flow {
        val payload = buildJsonObject {
            put("text", text)
            put("channel", channel)
            if (body.isNotEmpty()) put("body", body)
            if (sentAt != null) put("sent_at", sentAt.format(DateTimeFormatter.ISO_OFFSET_DATE_TIME))
            if (spoken) put("spoken", true)
        }
        val call = longHttp.newCall(post("/api/chat", payload.toString()))
        val response = try {
            call.execute()
        } catch (e: IOException) {
            throw KitError.Unreachable(e)
        }
        response.use {
            check(it)
            emit(ChatEvent.Accepted)
            val source = it.body?.source() ?: return@use
            try {
                while (true) {
                    currentCoroutineContext().ensureActive()
                    val line = source.readUtf8Line() ?: break
                    ChatEvent.parse(line)?.let { event -> emit(event) }
                }
            } catch (e: IOException) {
                throw KitError.Broken(e)
            } finally {
                call.cancel()
            }
        }
    }.flowOn(Dispatchers.IO)

    // ---- plumbing ----

    private fun url(path: String): HttpUrl =
        base.newBuilder().encodedPath(path).build()

    private fun request(url: HttpUrl, auth: Boolean = true): Request.Builder {
        val builder = Request.Builder().url(url).header("Accept", "application/json")
        if (auth) builder.header("Authorization", "Bearer $token")
        return builder
    }

    private fun get(path: String, auth: Boolean = true): Request = request(url(path), auth).get().build()

    private fun post(path: String, json: String): Request =
        request(url(path)).post(json.toRequestBody(JSON_TYPE)).build()

    private suspend fun call(request: Request, client: OkHttpClient = http): String {
        val call = client.newCall(request)
        val response = try {
            call.await()
        } catch (e: IOException) {
            throw KitError.Unreachable(e)
        }
        return response.use {
            check(it)
            try {
                it.body?.string() ?: ""
            } catch (e: IOException) {
                throw KitError.Unreachable(e)
            }
        }
    }

    private fun check(response: Response) {
        if (response.isSuccessful) return
        val detail = try {
            response.body?.string()?.let { text ->
                (KitJson.parseToJsonElement(text) as? JsonObject)?.str("detail") ?: text
            }
        } catch (e: Exception) {
            null
        } ?: response.message
        response.close()
        throw when (response.code) {
            401 -> KitError.BadToken()
            403 -> KitError.NotAllowed(detail)
            else -> KitError.Server(response.code, detail.ifBlank { "Kit answered ${response.code}" })
        }
    }

    private inline fun <reified T> decode(text: String): T = try {
        KitJson.decodeFromString<T>(text)
    } catch (e: Exception) {
        throw KitError.Server(200, "Kit's answer didn't make sense to this app")
    }

    companion object {
        private val JSON_TYPE = "application/json".toMediaType()
        private const val LONG_READ_S = 150L
        /** Messages before this id: the latest page of the whole history. */
        const val LATEST = Long.MAX_VALUE

        fun defaultHttp(): OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(8, TimeUnit.SECONDS)
            .readTimeout(30, TimeUnit.SECONDS)
            .writeTimeout(30, TimeUnit.SECONDS)
            .build()
    }
}

private suspend fun Call.await(): Response = suspendCancellableCoroutine { cont ->
    enqueue(object : Callback {
        override fun onResponse(call: Call, response: Response) {
            cont.resume(response)
        }

        override fun onFailure(call: Call, e: IOException) {
            if (!cont.isCancelled) cont.resumeWithException(e)
        }
    })
    cont.invokeOnCancellation {
        try {
            cancel()
        } catch (ignored: Throwable) {
        }
    }
}
