package io.github.senitage.kit.core

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.builtins.ListSerializer

/**
 * New versions of the app, from the Kit repo's GitHub Releases. GitHub builds the
 * app on every merge to main and publishes it as a release tagged
 * `android-v<version>` (.github/workflows/android.yml); test builds of a pull
 * request are pre-releases.
 */
object Updates {
    @Serializable
    data class Asset(
        val name: String = "",
        @SerialName("browser_download_url") val url: String = "",
        val size: Long = 0,
    )

    @Serializable
    data class Release(
        @SerialName("tag_name") val tag: String = "",
        val name: String = "",
        val body: String = "",
        val prerelease: Boolean = false,
        val draft: Boolean = false,
        val assets: List<Asset> = emptyList(),
    ) {
        /** The build number in its tag (`android-v0.1.57` is 57), or null if it isn't the app's. */
        val build: Int? get() = TAG.matchEntire(tag)?.groupValues?.get(2)?.toIntOrNull()

        val apk: Asset? get() = assets.firstOrNull { it.name.endsWith(".apk") }
    }

    private val TAG = Regex("^android-v(\\d+\\.\\d+)\\.(\\d+)$")

    fun releasesUrl(repo: String): String = "https://api.github.com/repos/$repo/releases?per_page=30"

    fun parse(json: String): List<Release> =
        KitJson.decodeFromString(ListSerializer(Release.serializer()), json)

    /** The newest app release newer than [build], with an APK; test builds only if [tests]. */
    fun newest(releases: List<Release>, build: Int, tests: Boolean = false): Release? =
        releases
            .filter { !it.draft && (tests || !it.prerelease) && it.apk != null }
            .filter { (it.build ?: 0) > build }
            .maxByOrNull { it.build ?: 0 }
}
