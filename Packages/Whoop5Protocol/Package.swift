// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "Whoop5Protocol",
    products: [
        .library(name: "Whoop5Protocol", targets: ["Whoop5Protocol"]),
        .executable(name: "whoop5-decode", targets: ["whoop5-decode"]),
    ],
    targets: [
        .target(name: "Whoop5Protocol", resources: [.copy("Resources/whoop5_protocol.json")]),
        .executableTarget(name: "whoop5-decode", dependencies: ["Whoop5Protocol"]),
        .testTarget(name: "Whoop5ProtocolTests", dependencies: ["Whoop5Protocol"],
                    resources: [.copy("Resources/golden.json")]),
    ]
)
