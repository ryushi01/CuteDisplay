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

@available(iOS 16.0, *)
extension KittyOwnerProofV6 {
    private struct Challenge: Decodable {
        let challenge: String
        let expires_at: Int
    }
    private struct GrantResponse: Decodable {
        let grant: String
        let expires_in: Int
    }

    /// Explicit owner action only. Must use a pinned/trusted HTTPS endpoint,
    /// a separately authenticated control credential, and a realtime session
    /// ID created by the gateway. Never use the S3/device key as owner proof.
    static func requestGrant(endpoint: URL, controlBearer: String,
                             sessionID: String) async throws -> String {
        guard endpoint.scheme == "https", !controlBearer.isEmpty,
              (8...100).contains(sessionID.count) else {
            throw NSError(domain: "KittyV6", code: 2)
        }
        func post(_ path: String, _ object: [String:String]) async throws -> Data {
            var req = URLRequest(url: endpoint.appendingPathComponent(path))
            req.httpMethod = "POST"
            req.timeoutInterval = 8
            req.addValue("application/json", forHTTPHeaderField: "Content-Type")
            req.addValue("Bearer " + controlBearer, forHTTPHeaderField: "Authorization")
            req.httpBody = try JSONSerialization.data(withJSONObject: object)
            let (data, response) = try await URLSession.shared.data(for: req)
            guard (response as? HTTPURLResponse)?.statusCode == 200,
                  data.count < 4096 else { throw NSError(domain:"KittyV6",code:3) }
            return data
        }
        let challengeData = try await post("owner/challenge", ["session_id":sessionID])
        let challenge = try JSONDecoder().decode(Challenge.self,from:challengeData)
        let signature = try signChallenge(sessionID:sessionID,challenge:challenge.challenge)
        let grantData = try await post("owner/verify", [
            "session_id":sessionID, "challenge":challenge.challenge,
            "signature":signature
        ])
        return try JSONDecoder().decode(GrantResponse.self,from:grantData).grant
    }
}
