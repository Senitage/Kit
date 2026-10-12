// Kit for Android's core: plain Kotlin, so it builds and tests without the Android
// SDK (`./gradlew -p core test`). The app includes it as a build of its own.
pluginManagement {
    repositories {
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositories {
        mavenCentral()
    }
}

rootProject.name = "core"
