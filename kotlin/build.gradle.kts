plugins {
    kotlin("jvm") version "2.0.21"
    `java-library`
}

group = "io.github.leonardseo"
version = "0.1.0"

repositories { mavenCentral() }

kotlin { jvmToolchain(17) }

dependencies {
    testImplementation(kotlin("test"))
    testImplementation("org.junit.jupiter:junit-jupiter:5.10.3")
    testRuntimeOnly("org.junit.platform:junit-platform-launcher:1.10.3")
}

tasks.test { useJUnitPlatform() }
