import Foundation
import CryptoKit
import LocalAuthentication
import Security

/// Optional V6 owner verification, independent of the existing BLE pairing.
/// An administrator must enroll this Secure Enclave public key on Ubuntu.
/// This helper is intentionally NOT invoked by the existing app automatically.
@available(iOS 16.0, *)
enum KittyOwnerProofV6 {
    static let keyTag = "com.cutedisplay.kitty.owner.v6"

    static func privateKey() throws -> SecureEnclave.P256.Signing.PrivateKey {
        let context = LAContext()
        context.localizedReason = "Authorize Kitty to update protected owner memories"
        // User presence must be required on every signature. Never fall back
        // to an unauthenticated software key when Secure Enclave is unavailable.
        if let stored = UserDefaults.standard.data(forKey: keyTag) {
            return try SecureEnclave.P256.Signing.PrivateKey(
                dataRepresentation: stored,
                authenticationContext: context
            )
        }
        let access = SecAccessControlCreateWithFlags(
            nil, kSecAttrAccessibleWhenUnlockedThisDeviceOnly,
            [.privateKeyUsage, .userPresence], nil
        )!
        let key = try SecureEnclave.P256.Signing.PrivateKey(
            accessControl: access, authenticationContext: context
        )
        UserDefaults.standard.set(key.dataRepresentation, forKey: keyTag)
        return key
    }

    /// Administrator-verifiable enrollment artifact; never an authorization
    /// request by itself. Server must pin/approve the public key out-of-band.
    static func enrollmentPublicKeyDER() throws -> Data {
        try privateKey().publicKey.derRepresentation
    }

    static func signChallenge(sessionID: String, challenge: String) throws -> String {
        guard (8...100).contains(sessionID.count),
              !challenge.isEmpty, challenge.count <= 128 else {
            throw NSError(domain: "KittyV6", code: 1)
        }
        let payload = Data("kitty-owner-v6\n\(sessionID)\n\(challenge)".utf8)
        let signature = try privateKey().signature(for: payload)
        return signature.derRepresentation.base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }
}
