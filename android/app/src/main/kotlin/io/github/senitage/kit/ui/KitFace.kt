package io.github.senitage.kit.ui

import android.annotation.SuppressLint
import android.graphics.Bitmap
import android.os.Build
import android.os.SystemClock
import android.view.HapticFeedbackConstants
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.viewinterop.AndroidView
import io.github.senitage.kit.core.Character
import io.github.senitage.kit.core.Director
import io.github.senitage.kit.core.GlowLook
import io.github.senitage.kit.core.Mirror
import io.github.senitage.kit.core.PhoneBody
import kotlinx.coroutines.delay

private fun seconds() = SystemClock.elapsedRealtime() / 1000.0

/**
 * Kit's face: his 3D face page from the brain when [page] is given and it has
 * loaded, otherwise the 2D glow face drawn here. Either way one [Director] moves
 * him; a tap is a boop and a long press a pat.
 */
@SuppressLint("SetJavaScriptEnabled")
@Composable
fun KitFace(director: Director, page: String?, modifier: Modifier = Modifier) {
    val face = director.face
    var frame by remember { mutableStateOf(face.tick(seconds())) }
    val drawn = remember { LookCache() }
    val mirror = remember { Mirror(face) }
    var web by remember { mutableStateOf<WebView?>(null) }
    var pageState by remember { mutableStateOf("none") } // none, loading or ready
    val view = LocalView.current

    DisposableEffect(director) {
        director.onBuzz = { kind ->
            view.performHapticFeedback(
                when (kind) {
                    "pat" -> HapticFeedbackConstants.LONG_PRESS
                    "pipe_up" ->
                        if (Build.VERSION.SDK_INT >= 30) HapticFeedbackConstants.CONFIRM else HapticFeedbackConstants.LONG_PRESS
                    else -> HapticFeedbackConstants.CONTEXT_CLICK
                },
            )
        }
        director.onShow = { show ->
            if (pageState == "ready") web?.evaluateJavascript(Mirror.show(show), null)
        }
        onDispose {
            director.onBuzz = {}
            director.onShow = {}
        }
    }

    // Every frame: move the face, and copy what changed to the 3D page.
    LaunchedEffect(face) {
        while (true) {
            withFrameNanos { }
            frame = face.tick(seconds())
            val w = web
            if (w != null && pageState != "none") {
                val calls = mirror.calls()
                if (calls.isNotEmpty()) w.evaluateJavascript("window.kit && (function(){${calls.joinToString("")}})();", null)
            }
        }
    }

    // Whether the 3D page has its kit API yet, and its model on screen.
    LaunchedEffect(page, web) {
        while (page != null && web != null) {
            web?.evaluateJavascript("window.kit ? (window.kit.ready ? 'ready' : 'loading') : 'none'") { answer ->
                val now = answer?.trim('"') ?: "none"
                if (now != pageState) {
                    if (pageState == "none") mirror.reset()
                    pageState = now
                }
            }
            delay(if (pageState == "ready") 5000 else 400)
        }
    }

    Box(
        modifier.pointerInput(director) {
            detectTapGestures(onTap = { director.boop() }, onLongPress = { director.pat() })
        },
    ) {
        if (page != null) {
            AndroidView(
                factory = { context ->
                    WebView(context).apply {
                        setBackgroundColor(android.graphics.Color.TRANSPARENT)
                        settings.javaScriptEnabled = true
                        settings.domStorageEnabled = true
                        isVerticalScrollBarEnabled = false
                        isHorizontalScrollBarEnabled = false
                        webViewClient = object : WebViewClient() {
                            override fun onPageStarted(view: WebView?, url: String?, favicon: Bitmap?) {
                                pageState = "none"
                            }
                        }
                        tag = page
                        loadUrl(page)
                        web = this
                    }
                },
                // Only a new address reloads (the page's own address can change as it runs).
                update = {
                    if (it.tag != page) {
                        it.tag = page
                        it.loadUrl(page)
                    }
                },
                onRelease = {
                    web = null
                    pageState = "none"
                    it.destroy()
                },
                modifier = Modifier.fillMaxSize().alpha(if (pageState == "ready") 1f else 0f),
            )
        }
        if (page == null || pageState != "ready") {
            Canvas(Modifier.fillMaxSize()) {
                val character = face.character
                val look = drawn.look(character)
                if (look != null) paintGlow(look, frame, character.hasMoodColours)
            }
        }
    }
}

/** The 2D look of the character being drawn, read again only when the character changes. */
private class LookCache {
    private var character: Character? = null
    private var look: GlowLook? = null

    fun look(c: Character): GlowLook? {
        if (c !== character) {
            character = c
            look = c.look(PhoneBody.KIND)?.let { GlowLook.from(it) }
        }
        return look
    }
}
