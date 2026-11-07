import org.jetbrains.kotlin.gradle.dsl.JvmTarget
import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// Release signing key lives outside the repo (~/.transsnip/keystore.properties:
// storeFile, storePassword, keyAlias, keyPassword). Without it, release builds
// come out unsigned — nothing secret is ever in git.
val releaseKey = Properties().apply {
    val f = File(System.getProperty("user.home"), ".transsnip/keystore.properties")
    if (f.exists()) f.inputStream().use { load(it) }
}

android {
    namespace = "io.github.orms147.transsnip"
    compileSdk = 36

    defaultConfig {
        applicationId = "io.github.orms147.transsnip"
        minSdk = 26
        targetSdk = 36
        versionCode = 4
        versionName = "0.3.1"
        // Phones are arm64; x86_64 is the emulator. Keeps ML Kit's native libs small.
        ndk { abiFilters += listOf("arm64-v8a", "x86_64") }
    }

    buildFeatures {
        buildConfig = true
    }

    signingConfigs {
        if (releaseKey.isNotEmpty()) create("release") {
            storeFile = file(releaseKey.getProperty("storeFile"))
            storePassword = releaseKey.getProperty("storePassword")
            keyAlias = releaseKey.getProperty("keyAlias")
            keyPassword = releaseKey.getProperty("keyPassword")
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            signingConfig = signingConfigs.findByName("release")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

kotlin {
    compilerOptions {
        jvmTarget.set(JvmTarget.JVM_17)
    }
}

dependencies {
    // On-device OCR for video/images/games. Bundled model: offline, no Play services needed.
    implementation("com.google.mlkit:text-recognition-chinese:16.0.1")
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")   // real org.json; android.jar only has stubs
}
