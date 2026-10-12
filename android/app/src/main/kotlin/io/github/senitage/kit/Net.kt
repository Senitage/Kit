package io.github.senitage.kit

import android.content.Context
import android.content.Intent
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities

/** The phone's network: whether a VPN (Tailscale) is up, and hearing when it changes. */
object Net {
    const val TAILSCALE = "com.tailscale.ipn"

    fun vpnUp(context: Context): Boolean {
        val cm = context.getSystemService(ConnectivityManager::class.java) ?: return true
        @Suppress("DEPRECATION")
        return cm.allNetworks.any { cm.getNetworkCapabilities(it)?.hasTransport(NetworkCapabilities.TRANSPORT_VPN) == true }
    }

    fun tailscaleInstalled(context: Context): Boolean =
        context.packageManager.getLaunchIntentForPackage(TAILSCALE) != null

    fun openTailscale(context: Context) {
        val intent = context.packageManager.getLaunchIntentForPackage(TAILSCALE)
            ?: Intent(Intent.ACTION_VIEW, android.net.Uri.parse("https://play.google.com/store/apps/details?id=$TAILSCALE"))
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        context.startActivity(intent)
    }

    /** Calls [changed] whenever a network comes or goes (Wi-Fi, mobile data, the VPN). */
    fun watch(context: Context, changed: () -> Unit): () -> Unit {
        val cm = context.getSystemService(ConnectivityManager::class.java) ?: return {}
        val callback = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) = changed()

            override fun onLost(network: Network) = changed()
        }
        cm.registerDefaultNetworkCallback(callback)
        return { runCatching { cm.unregisterNetworkCallback(callback) } }
    }
}
