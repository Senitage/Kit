package io.github.senitage.kit.core

import java.net.URI
import java.net.URLDecoder

/** Kit's brain listens on this port unless the address says otherwise. */
const val KIT_PORT = 8600

object KitAddress {
    /**
     * Kit's address as typed into the app, made into a base URL: `192.168.1.50`,
     * `kit-server`, `kit-server:9000` or `http://kit-server:8600/` all work. Null when
     * it can't be an address.
     */
    fun normalize(input: String): String? {
        var text = input.trim()
        if (text.isEmpty() || text.any { it.isWhitespace() }) return null
        if (!text.contains("://")) text = "http://$text"
        val uri = try {
            URI(text)
        } catch (e: Exception) {
            return null
        }
        val scheme = uri.scheme?.lowercase() ?: return null
        if (scheme != "http" && scheme != "https") return null
        val host = uri.host ?: return null
        val port = if (uri.port > 0) uri.port else if (scheme == "https") -1 else KIT_PORT
        val shownHost = if (host.contains(':') && !host.startsWith("[")) "[$host]" else host
        return if (port > 0) "$scheme://$shownHost:$port" else "$scheme://$shownHost"
    }
}

/** What `kit pair` puts in its QR code: `kit://pair?url=...&name=...&token=...`. */
data class PairingLink(val url: String, val name: String, val token: String) {
    companion object {
        fun parse(link: String): PairingLink? {
            val text = link.trim()
            if (!text.startsWith("kit://pair", ignoreCase = true)) return null
            val query = text.substringAfter('?', "")
            val values = query.split('&').filter { it.isNotEmpty() }.associate { part ->
                val key = part.substringBefore('=')
                val value = part.substringAfter('=', "")
                decode(key) to decode(value)
            }
            val url = KitAddress.normalize(values["url"] ?: return null) ?: return null
            val token = values["token"]?.takeIf { it.isNotBlank() } ?: return null
            val name = values["name"]?.takeIf { DeviceName.valid(it) } ?: "phone"
            return PairingLink(url, name, token)
        }

        private fun decode(text: String): String = URLDecoder.decode(text, Charsets.UTF_8)
    }
}

object DeviceName {
    /** The names Kit accepts for a paired device (kit.devices). */
    private val PATTERN = Regex("^[a-z0-9][a-z0-9-]{0,39}$")

    fun valid(name: String): Boolean = PATTERN.matches(name)

    /** A name Kit accepts, made from what was typed: "My Pixel 8" -> "my-pixel-8". */
    fun tidy(typed: String): String {
        val words = typed.lowercase()
            .replace("'", "")
            .replace(Regex("[^a-z0-9]+"), "-")
            .trim('-')
            .take(40)
            .trimEnd('-')
        return words.ifEmpty { "phone" }
    }
}
