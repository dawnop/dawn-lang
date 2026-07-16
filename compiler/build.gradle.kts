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
    // Maven dependency resolution for dawn.toml's [java-deps] (docs/package-design.md §A.1).
    // `interface` is the pure-Java, fully shaded artifact — NOT `io.get-coursier::coursier`,
    // which is a Scala API needing a Scala runtime. The shading is why this one is safe:
    // maven-resolver and MIMA would each put their own asm on the classpath, colliding with
    // the asm we generate bytecode with. slf4j-api is coursier's one unshaded dependency;
    // bind it to a no-op so resolution stays quiet.
    implementation("io.get-coursier:interface:1.0.28")
    runtimeOnly("org.slf4j:slf4j-nop:2.0.16")
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
