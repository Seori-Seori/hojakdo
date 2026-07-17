plugins {
    id("com.android.application")
}

android {
    namespace = "com.seori.hojakdo"
    compileSdk = 33

    defaultConfig {
        applicationId = "com.seori.hojakdo"
        minSdk = 33
        targetSdk = 33
        versionCode = 6
        versionName = "4.2.0"
    }

    buildTypes {
        debug {
            isMinifyEnabled = true
        }
        release {
            isMinifyEnabled = true
            isShrinkResources = false
            signingConfig = signingConfigs.getByName("debug")
        }
    }
}

val generatedResDir = layout.buildDirectory.dir("generated/hojakdo-res")
val sourceLayerDir = rootProject.file("assets/layers/v4/drawable")
val sourceAnimationDir = rootProject.file("assets/layers/v4/animations")
val sourcePreview = rootProject.file(
    "prototype/hojakdo_v4/output/hojakdo_v4_integrated_static.png"
)

val prepareHojakdoAssets by tasks.registering {
    inputs.dir(sourceLayerDir)
    inputs.dir(sourceAnimationDir)
    inputs.file(sourcePreview)
    outputs.dir(generatedResDir)

    doLast {
        val drawableDir = generatedResDir.get().dir("drawable-nodpi").asFile
        drawableDir.mkdirs()

        sourceLayerDir.listFiles { file -> file.extension == "png" }
            ?.forEach { file ->
                file.copyTo(drawableDir.resolve(file.name), overwrite = true)
            }
        sourceAnimationDir.listFiles { file -> file.extension == "gif" }
            ?.forEach { file ->
                file.copyTo(drawableDir.resolve(file.name), overwrite = true)
            }

        sourcePreview.copyTo(drawableDir.resolve("preview.png"), overwrite = true)
    }
}

android.sourceSets.getByName("main").res.srcDir(generatedResDir)
tasks.matching { it.name == "preBuild" }.configureEach {
    dependsOn(prepareHojakdoAssets)
}
