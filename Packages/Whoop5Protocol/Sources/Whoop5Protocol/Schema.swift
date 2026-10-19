import Foundation

/// Name tables from the bundled canonical `whoop5_protocol.json` (byte-identical to `protocol/`).
public final class Whoop5Schema {
    public static let shared = Whoop5Schema()

    public let json: [String: Any]
    private let commands: [String: Any], events: [String: Any], packetTypes: [String: Any]

    private init() {
        let url = Bundle.module.url(forResource: "whoop5_protocol", withExtension: "json")!
        // swiftlint:disable:next force_try
        json = (try! JSONSerialization.jsonObject(with: Data(contentsOf: url))) as! [String: Any]
        commands = json["commands"] as? [String: Any] ?? [:]
        events = json["events"] as? [String: Any] ?? [:]
        packetTypes = json["packet_types"] as? [String: Any] ?? [:]
    }

    public func commandName(_ n: UInt8) -> String { commands[String(n)] as? String ?? "UNKNOWN_\(n)" }
    public func eventName(_ n: UInt8) -> String { events[String(n)] as? String ?? "UNKNOWN_\(n)" }
    public func packetName(_ n: UInt8) -> String { packetTypes[String(n)] as? String ?? "UNKNOWN_\(n)" }

    /// Commands that can brick, wipe or permanently alter a strap. A client should never send these.
    public var destructiveCommands: Set<UInt8> {
        Set((commands["destructive"] as? [Int] ?? []).map { UInt8($0) })
    }
}
