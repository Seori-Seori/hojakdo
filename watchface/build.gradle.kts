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
        versionCode = 8
        versionName = "4.3.1"
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
val sourceFrameDir = rootProject.file("assets/layers/v4/frames")
val sourcePreview = rootProject.file(
    "prototype/hojakdo_v4/output/hojakdo_v4_integrated_static.png"
)

val prepareHojakdoAssets by tasks.registering {
    inputs.dir(sourceLayerDir)
    inputs.dir(sourceFrameDir)
    inputs.file(sourcePreview)
    outputs.dir(generatedResDir)

    doLast {
        val drawableDir = generatedResDir.get().dir("drawable-nodpi").asFile
        drawableDir.deleteRecursively()
        drawableDir.mkdirs()

        sourceLayerDir.listFiles { file -> file.extension == "png" }
            ?.forEach { file ->
                file.copyTo(drawableDir.resolve(file.name), overwrite = true)
            }
        sourceFrameDir.listFiles { file -> file.isDirectory }
            ?.sortedBy { directory -> directory.name }
            ?.forEach { animationDir ->
                animationDir.listFiles { file -> file.extension == "png" }
                    ?.sortedBy { file -> file.name }
                    ?.forEach { file ->
                        file.copyTo(
                            drawableDir.resolve("${animationDir.name}_${file.name}"),
                            overwrite = true,
                        )
                    }
            }

        sourcePreview.copyTo(drawableDir.resolve("preview.png"), overwrite = true)
    }
}

android.sourceSets.getByName("main").res.srcDir(generatedResDir)
tasks.matching { it.name == "preBuild" }.configureEach {
    dependsOn(prepareHojakdoAssets)
}
