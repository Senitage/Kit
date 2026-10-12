package io.github.senitage.kit

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import io.github.senitage.kit.core.PairingLink
import io.github.senitage.kit.ui.Root
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {
    private val kit: Kit get() = (application as KitApp).kit

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        take(intent)
        setContent { Root(kit) }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        take(intent)
    }

    /**
     * How the app was opened: a `kit pair` QR code, text shared to Kit from another
     * app, a home screen shortcut, or a notification.
     */
    private fun take(intent: Intent?) {
        intent ?: return
        intent.dataString?.let { PairingLink.parse(it) }?.let {
            kit.pairingLink.value = it
            return
        }
        when (intent.action) {
            Intent.ACTION_SEND -> if (intent.type?.startsWith("text/") == true) {
                val text = intent.getStringExtra(Intent.EXTRA_TEXT)?.trim().orEmpty()
                val subject = intent.getStringExtra(Intent.EXTRA_SUBJECT)?.trim().orEmpty()
                val shared = listOf(subject, text).filter { it.isNotEmpty() }.joinToString("\n")
                if (shared.isNotEmpty()) kit.draft.value = shared
                kit.tab.value = Tab.CHAT
            }
            ACTION_NEW_CHAT -> {
                kit.tab.value = Tab.CHAT
                kit.scope.launch { kit.conversation.newChat() }
            }
            ACTION_QUIET -> {
                kit.tab.value = Tab.KIT
                kit.scope.launch { kit.quiet(60) }
            }
            ACTION_OPEN -> kit.tab.value = Tab.CHAT
        }
        intent.action = null
    }

    companion object {
        const val ACTION_OPEN = "io.github.senitage.kit.OPEN"
        const val ACTION_NEW_CHAT = "io.github.senitage.kit.NEW_CHAT"
        const val ACTION_QUIET = "io.github.senitage.kit.QUIET"
    }
}
