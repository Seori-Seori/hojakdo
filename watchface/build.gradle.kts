import java.awt.image.BufferedImage
import javax.imageio.ImageIO

plugins {
    id("com.android.application")
}

android {
    enableKotlin = false
    namespace = "com.seori.hojakdo"
    compileSdk = 33

    defaultConfig {
        applicationId = "com.seori.hojakdo"
        minSdk = 33
        targetSdk = 33
        versionCode = 1
        versionName = "0.1.0"
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
val sourceLayerDir = rootProject.file("assets/layers/mvp")

fun mirrorAroundAnchor(source: BufferedImage, anchorX: Double): BufferedImage {
    val result = BufferedImage(source.width, source.height, BufferedImage.TYPE_INT_ARGB)
    for (y in 0 until source.height) {
        for (x in 0 until source.width) {
            val targetX = kotlin.math.round(2.0 * anchorX - x).toInt()
            if (targetX in 0 until source.width) {
                result.setRGB(targetX, y, source.getRGB(x, y))
            }
        }
    }
    return result
}

val prepareHojakdoAssets by tasks.registering {
    inputs.dir(sourceLayerDir)
    outputs.dir(generatedResDir)

    doLast {
        val drawableDir = generatedResDir.get().dir("drawable-nodpi").asFile
        drawableDir.mkdirs()

        val copied = listOf(
            "clean_background",
            "hour_branch",
            "minute_branch",
            "tiger_head",
            "tiger_pupils"
        )
        copied.forEach { name ->
            sourceLayerDir.resolve("$name.png").copyTo(drawableDir.resolve("$name.png"), overwrite = true)
        }

        sourceLayerDir.resolve("hour_magpie.png")
            .copyTo(drawableDir.resolve("hour_magpie_normal.png"), overwrite = true)
        sourceLayerDir.resolve("minute_magpie.png")
            .copyTo(drawableDir.resolve("minute_magpie_normal.png"), overwrite = true)

        val hourBird = ImageIO.read(sourceLayerDir.resolve("hour_magpie.png"))
        val minuteBird = ImageIO.read(sourceLayerDir.resolve("minute_magpie.png"))

        ImageIO.write(
            mirrorAroundAnchor(hourBird, 305.0 * 1254.0 / 450.0),
            "png",
            drawableDir.resolve("hour_magpie_mirrored.png")
        )
        ImageIO.write(
            mirrorAroundAnchor(minuteBird, 159.0 * 1254.0 / 450.0),
            "png",
            drawableDir.resolve("minute_magpie_mirrored.png")
        )

        sourceLayerDir.resolve("clean_background.png")
            .copyTo(drawableDir.resolve("preview.png"), overwrite = true)
    }
}

android.sourceSets.getByName("main").res.srcDir(generatedResDir)
tasks.matching { it.name == "preBuild" }.configureEach {
    dependsOn(prepareHojakdoAssets)
}
