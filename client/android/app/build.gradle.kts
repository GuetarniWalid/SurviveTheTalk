plugins {
    id("com.android.application")
    id("kotlin-android")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

android {
    namespace = "com.surviveTheTalk.client"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = JavaVersion.VERSION_17.toString()
    }

    defaultConfig {
        // TODO: Specify your own unique Application ID (https://developer.android.com/studio/build/application-id.html).
        applicationId = "com.surviveTheTalk.client"
        // You can update the following values to match your application needs.
        // For more information, see: https://flutter.dev/to/review-gradle-config.
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    buildTypes {
        release {
            // TODO: Add your own signing config for the release build.
            // Signing with the debug keys for now, so `flutter run --release` works.
            signingConfig = signingConfigs.getByName("debug")
        }
    }
}

flutter {
    source = "../.."
}

dependencies {
    // Story 6.3b — our native AudioClockChannel.kt accesses libwebrtc's
    // JavaAudioDeviceModule.PlaybackSamplesReadyCallback type via the
    // flutter_webrtc plugin's reflection path. The type lives in this
    // io.github.webrtc-sdk AAR; we depend on the same version
    // flutter_webrtc itself pulls in so they share one classloader and
    // the type is resolvable at our compile time.
    implementation("io.github.webrtc-sdk:android:137.7151.04")

    // Story 6.3b — JVM unit tests for the DSP path (Fft,
    // FormantVisemeAnalyzer). Pure-Kotlin code with no Android API
    // surface inside the analyzer, so JUnit on stock JVM is enough —
    // Robolectric is not needed. Run with `./gradlew :app:testDebugUnitTest`.
    testImplementation("junit:junit:4.13.2")
}
