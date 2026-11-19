// swift-tools-version:5.9
import PackageDescription
import Foundation

// Links NOOP's own scoring code from a local checkout, so nothing of NOOP is copied here. The default is a detached worktree of
// upstream ryanbr/noop main next to this repository; a fork or feature branch would score a modified NOOP.
let noop = ProcessInfo.processInfo.environment["NOOP_DIR"] ?? "../../../noop-upstream"

let package = Package(
    name: "noop-scores",
    platforms: [.macOS(.v13)],
    dependencies: [
        .package(path: "\(noop)/Packages/StrandAnalytics"),
        .package(path: "\(noop)/Packages/WhoopProtocol"),
    ],
    targets: [
        .executableTarget(name: "noop-scores", dependencies: [
            .product(name: "StrandAnalytics", package: "StrandAnalytics"),
            .product(name: "WhoopProtocol", package: "WhoopProtocol"),
        ]),
    ]
)
