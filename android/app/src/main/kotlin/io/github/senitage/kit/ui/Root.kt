package io.github.senitage.kit.ui

import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import io.github.senitage.kit.Kit

/** Pairing until the phone knows Kit (or a pairing code arrives), then the chat. */
@Composable
fun Root(kit: Kit) {
    KitTheme {
        val paired by kit.paired.collectAsStateWithLifecycle()
        val link by kit.pairingLink.collectAsStateWithLifecycle()
        Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
            if (!paired || link != null) PairScreen(kit) else ChatScreen(kit)
        }
    }
}
