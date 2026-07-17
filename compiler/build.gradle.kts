plugins {
    kotlin("jvm") version "2.0.21"
    application
    id("org.jlleitschuh.gradle.ktlint") version "14.2.0"
    // Report only, no verification rule: a coverage threshold gets defended, and
    // tests written to defend a number are worse than no number. What is useful
    // is seeing which parts of a compiler 1170 tests never reach.
    id("org.jetbrains.kotlinx.kover") version "0.9.8"
}

version = "0.1.0"

repositories {
    mavenCentral()
}

// The commit is half of what `dawn --version` needs to be useful: between tags,
// "0.1.0" names a range of builds, and the one a bug report means is the commit.
// ignoreExitValue + orElse so a source tarball with no .git still builds.
val gitCommit: Provider<String> =
    providers.exec {
        commandLine("git", "rev-parse", "--short", "HEAD")
        isIgnoreExitValue = true
    }.standardOutput.asText.map { it.trim() }.map { it.ifEmpty { "unknown" } }.orElse("unknown")

// Written as a resource rather than read back off the jar manifest: the fat jar
// merges in every dependency's manifest, so "read our own" is a guessing game.
// A resource we generate is unambiguous, and works the same under `gradle run`.
val generateBuildInfo by tasks.registering {
    val outDir = layout.buildDirectory.dir("generated/buildinfo")
    val versionValue = providers.provider { project.version.toString() }
    inputs.property("version", versionValue)
    inputs.property("commit", gitCommit)
    outputs.dir(outDir)
    doLast {
        val f = outDir.get().file("dawn-build.properties").asFile
        f.parentFile.mkdirs()
        f.writeText("version=${versionValue.get()}\ncommit=${gitCommit.get()}\n")
    }
}

sourceSets.main {
    resources.srcDir(generateBuildInfo)
}

// For release.yml to check the tag against what is actually being built.
tasks.register("printVersion") {
    val v = project.version.toString()
    doLast { println(v) }
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
    // Stay dawn.jar once `version` is set, or Gradle would name it dawn-0.1.0.jar.
    // The filename is an interface: bin/dawn, site/build.sh and the dawnop-site
    // build all reach for it by name. The version belongs in --version, not here.
    archiveVersion.set("")
    manifest {
        attributes["Main-Class"] = "dawn.cli.MainKt"
        attributes["Implementation-Version"] = project.version.toString()
    }
    duplicatesStrategy = DuplicatesStrategy.EXCLUDE
    // signed dependency jars (gson): merged signature files would fail verification
    exclude("META-INF/*.SF", "META-INF/*.DSA", "META-INF/*.RSA")
    from(sourceSets.main.get().output)
    dependsOn(configurations.runtimeClasspath)
    from({ configurations.runtimeClasspath.get().filter { it.name.endsWith("jar") }.map { zipTree(it) } })
}
