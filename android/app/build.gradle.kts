import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

// GitHub numbers each build (.github/workflows/android.yml); a build on a PC is 1.
val buildNumber = (System.getenv("KIT_BUILD_NUMBER") ?: "1").toInt()
// The signing key comes from GitHub's secrets, never the repo. Without it the build
// is signed with a throwaway key, which can't update an installed Kit.
val keystore: String? = System.getenv("KIT_KEYSTORE_FILE")?.takeIf { it.isNotBlank() }
// Firebase, for Kit's nudges (content-free pushes that wake the app to look for a
// pipe-up). The project's ids come from GitHub's variables, never the repo; without
// them the app has no push and looks for pipe-ups now and then instead. See
// docs/4 Guides/Phone Stage 2 - He's With You.md.
val firebase = listOf("PROJECT_ID", "APP_ID", "API_KEY", "SENDER_ID")
    .associateWith { System.getenv("KIT_FIREBASE_$it")?.trim().orEmpty() }

android {
    namespace = "io.github.senitage.kit"
    compileSdk = 35

    defaultConfig {
        applicationId = "io.github.senitage.kit"
        minSdk = 26
        targetSdk = 35
        versionCode = buildNumber
        versionName = "0.1.$buildNumber"
        buildConfigField("String", "REPO", "\"${System.getenv("GITHUB_REPOSITORY") ?: "Senitage/Kit"}\"")
        buildConfigField("boolean", "TEST_BUILD", (!System.getenv("KIT_BUILD_PULL").isNullOrBlank()).toString())
        buildConfigField("boolean", "SIGNED", (keystore != null).toString())
        firebase.forEach { (name, value) -> buildConfigField("String", "FIREBASE_$name", "\"$value\"") }
        buildConfigField("boolean", "FIREBASE", firebase.values.all { it.isNotBlank() }.toString())
    }

    signingConfigs {
        create("kit") {
            if (keystore != null) {
                storeFile = file(keystore)
                storePassword = System.getenv("KIT_KEYSTORE_PASSWORD")
                keyAlias = System.getenv("KIT_KEY_ALIAS")?.takeIf { it.isNotBlank() } ?: "kit"
                keyPassword = System.getenv("KIT_KEYSTORE_PASSWORD")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName(if (keystore != null) "kit" else "debug")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    packaging {
        resources.excludes += "/META-INF/{AL2.0,LGPL2.1}"
    }

    sourceSets["main"].assets.srcDir(layout.buildDirectory.dir("generated/kit-assets"))
}

kotlin {
    compilerOptions {
        jvmTarget.set(JvmTarget.JVM_17)
    }
}

// Kit 2D's character sheet, so he can be drawn before Kit sends his own.
val copyCharacter = tasks.register<Copy>("copyKitCharacter") {
    from(rootDir.resolve("../src/kit/face/characters/kit2d.json"))
    into(layout.buildDirectory.dir("generated/kit-assets"))
}
tasks.named("preBuild") { dependsOn(copyCharacter) }

dependencies {
    implementation("io.github.senitage.kit:core")

    implementation(platform("androidx.compose:compose-bom:2024.12.01"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-graphics")
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-core")
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.7")
    implementation("androidx.lifecycle:lifecycle-process:2.8.7")
    implementation("androidx.work:work-runtime-ktx:2.10.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")
    // Nudges (Firebase Cloud Messaging), the home screen widget and its drawing.
    implementation("com.google.firebase:firebase-messaging:24.1.0")
    implementation("androidx.glance:glance-appwidget:1.1.1")
    implementation("androidx.glance:glance-material3:1.1.1")
}
