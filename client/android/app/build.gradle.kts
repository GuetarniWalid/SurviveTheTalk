import java.util.Properties
import java.io.FileInputStream

plugins {
    id("com.android.application")
    id("kotlin-android")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

// Story 10.3 — release signing credentials are loaded from a git-ignored
// `android/key.properties` (never committed; see android/.gitignore). The
// file is absent on dev machines that don't hold the upload keystore, in
// which case release builds fall back to debug signing below so a plain
// `flutter run --release` still works locally. The real upload keystore is
// owned + backed up by Walid (DEC-5) and lives off-repo.
val keystoreProperties = Properties()
val keystorePropertiesFile = rootProject.file("key.properties")
val hasReleaseKeystore = keystorePropertiesFile.exists()
if (hasReleaseKeystore) {
    keystoreProperties.load(FileInputStream(keystorePropertiesFile))
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
        // Story 8.1 — the `in_app_purchase` 3.x plugin (Google Play Billing)
        // requires Android SDK 24+. Flutter's default already resolves to 24,
        // but we encode the floor explicitly so a future Flutter that lowered
        // the default can't silently break the billing integration.
        minSdk = maxOf(flutter.minSdkVersion, 24)
        targetSdk = flutter.targetSdkVersion
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    signingConfigs {
        create("release") {
            // Populated only when key.properties is present; otherwise the
            // release build falls back to the debug config below so the
            // empty release config is never actually referenced.
            if (hasReleaseKeystore) {
                keyAlias = keystoreProperties.getProperty("keyAlias")
                keyPassword = keystoreProperties.getProperty("keyPassword")
                storeFile = keystoreProperties.getProperty("storeFile")?.let { file(it) }
                storePassword = keystoreProperties.getProperty("storePassword")
            }
        }
    }

    buildTypes {
        release {
            // Use the real upload key when key.properties exists (CI / release
            // machine); fall back to debug signing locally so `flutter run
            // --release` still works without the keystore (Story 10.3 / DEC-5).
            signingConfig = if (hasReleaseKeystore) {
                signingConfigs.getByName("release")
            } else {
                signingConfigs.getByName("debug")
            }
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
