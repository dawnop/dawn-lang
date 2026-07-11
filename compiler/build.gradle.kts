plugins {
    kotlin("jvm") version "2.0.21"
    application
}

repositories {
    mavenCentral()
}

dependencies {
    implementation("org.ow2.asm:asm:9.7.1")
    testImplementation(kotlin("test"))
}

kotlin {
    jvmToolchain(21)
}

application {
    mainClass.set("dawn.cli.MainKt")
}

tasks.test {
    useJUnitPlatform()
    testLogging { events("failed", "skipped") }
}

// Self-contained jar: the dawn CLI itself (bundling Kotlin stdlib and ASM), used by bin/dawn
tasks.register<Jar>("fatJar") {
    archiveBaseName.set("dawn")
    manifest { attributes["Main-Class"] = "dawn.cli.MainKt" }
    duplicatesStrategy = DuplicatesStrategy.EXCLUDE
    from(sourceSets.main.get().output)
    dependsOn(configurations.runtimeClasspath)
    from({ configurations.runtimeClasspath.get().filter { it.name.endsWith("jar") }.map { zipTree(it) } })
}
