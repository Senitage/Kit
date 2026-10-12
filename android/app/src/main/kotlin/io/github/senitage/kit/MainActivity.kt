package io.github.senitage.kit

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import io.github.senitage.kit.core.PairingLink
import io.github.senitage.kit.ui.Root

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

    /** Opened from a `kit pair` QR code: offer to pair with it. */
    private fun take(intent: Intent?) {
        val link = intent?.dataString?.let { PairingLink.parse(it) } ?: return
        kit.pairingLink.value = link
    }
}
