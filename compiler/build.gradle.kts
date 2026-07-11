plugins {
    kotlin("jvm") version "2.0.21"
    application
}

repositories {
    mavenCentral()
}

dependencies {
    implementation("org.ow2.asm:asm:9.7.1")
    implementation("org.eclipse.lsp4j:org.eclipse.lsp4j:0.21.1")
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
    // Forward -DupdateGolden=true to the test JVM so golden files can be regenerated.
    System.getProperty("updateGolden")?.let { systemProperty("updateGolden", it) }
}

// Self-contained jar: the dawn CLI itself (bundling Kotlin stdlib and ASM), used by bin/dawn
tasks.register<Jar>("fatJar") {
    archiveBaseName.set("dawn")
    manifest { attributes["Main-Class"] = "dawn.cli.MainKt" }
    duplicatesStrategy = DuplicatesStrategy.EXCLUDE
    // signed dependency jars (gson): merged signature files would fail verification
    exclude("META-INF/*.SF", "META-INF/*.DSA", "META-INF/*.RSA")
    from(sourceSets.main.get().output)
    dependsOn(configurations.runtimeClasspath)
    from({ configurations.runtimeClasspath.get().filter { it.name.endsWith("jar") }.map { zipTree(it) } })
}
