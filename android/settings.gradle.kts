// Kit for Android: the phone app (one more of Kit's bodies). See
// docs/2 How Kit Works/Phone App.md. `core` is plain Kotlin (talking to Kit, the
// chat, the face rig) and builds anywhere; `app` is the Android app and needs the
// Android SDK.
pluginManagement {
    repositories {
        google {
            content {
                includeGroupByRegex("com\\.android.*")
                includeGroupByRegex("com\\.google.*")
                includeGroupByRegex("androidx.*")
            }
        }
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google {
            content {
                includeGroupByRegex("com\\.android.*")
                includeGroupByRegex("com\\.google.*")
                includeGroupByRegex("androidx.*")
            }
        }
        mavenCentral()
    }
}

rootProject.name = "kit-android"
includeBuild("core")
include(":app")
