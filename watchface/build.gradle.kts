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
        versionCode = 9
        versionName = "4.3.2"
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
val sourceWatchFaceXml = rootProject.file("watchface/src/main/res/raw/watchface.xml")
val sourcePreview = rootProject.file(
    "prototype/hojakdo_v4/output/hojakdo_v4_integrated_static.png"
)

val prepareHojakdoAssets by tasks.registering {
    inputs.dir(sourceLayerDir)
    inputs.dir(sourceFrameDir)
    inputs.file(sourceWatchFaceXml)
    inputs.file(sourcePreview)
    outputs.dir(generatedResDir)

    doLast {
        val drawableDir = generatedResDir.get().dir("drawable-nodpi").asFile
        drawableDir.deleteRecursively()
        drawableDir.mkdirs()

        // Package only resources actually referenced by the generated WFF.
        // Review thumbnails and archival middle frames stay in Git but do not
        // consume runtime resource or decoded-memory budget.
        val imageResourceRegex = Regex("""<Image\\s+resource="([^"]+)"""")
        val runtimeResources = imageResourceRegex.findAll(sourceWatchFaceXml.readText())
            .map { match -> match.groupValues[1] }
            .toSet()

        sourceLayerDir.listFiles { file -> file.extension == "png" }
            ?.filter { file -> file.nameWithoutExtension in runtimeResources }
            ?.forEach { file ->
                file.copyTo(drawableDir.resolve(file.name), overwrite = true)
            }
        sourceFrameDir.listFiles { file -> file.isDirectory }
            ?.sortedBy { directory -> directory.name }
            ?.forEach { animationDir ->
                animationDir.listFiles { file -> file.extension == "png" }
                    ?.sortedBy { file -> file.name }
                    ?.forEach { file ->
                        val resourceName =
                            "${animationDir.name}_${file.nameWithoutExtension}"
                        if (resourceName in runtimeResources) {
                            file.copyTo(
                                drawableDir.resolve("${resourceName}.png"),
                                overwrite = true,
                            )
                        }
                    }
            }

        sourcePreview.copyTo(drawableDir.resolve("preview.png"), overwrite = true)
    }
}

android.sourceSets.getByName("main").res.srcDir(generatedResDir)
tasks.matching { it.name == "preBuild" }.configureEach {
    dependsOn(prepareHojakdoAssets)
}
