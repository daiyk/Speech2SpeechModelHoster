import CryptoKit
import Foundation

// Sparkle's current private-key format is a base64-encoded 32-byte Ed25519 seed.
guard let line = readLine(), let seed = Data(base64Encoded: line),
      let key = try? Curve25519.Signing.PrivateKey(rawRepresentation: seed) else {
    FileHandle.standardError.write(Data("Expected a base64-encoded 32-byte Sparkle private key.\n".utf8))
    exit(1)
}
print(key.publicKey.rawRepresentation.base64EncodedString())
