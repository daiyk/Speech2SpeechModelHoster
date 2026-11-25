import Foundation

@main
struct ModelChecks {
    static func main() {
        let model = ServerModel()
        model.consume(Data("REACHY_EVENT {\"kind\":\"connected\",\"id\":\"test\",\"peer\":\"127.0.0.1:1234\"}\n".utf8))
        assert(model.clients.count == 1)
        // A UTF-8 protocol line may arrive in multiple pipe chunks.
        let line = Data("REACHY_EVENT {\"kind\":\"message\",\"id\":\"test\",\"direction\":\"Client\",\"text\":\"conversation.item.create: Hello: café\"}\n".utf8)
        model.consume(line.prefix(line.count - 4))
        assert(model.messages.isEmpty)
        model.consume(line.suffix(4))
        assert(model.messages.count == 1 && model.messages[0].text == "Hello: café")
        model.record("response.output_audio_transcript.delta: Hello", direction: "Server")
        assert(model.request == "Speaking" && model.messages.count == 1)
        model.record("response.output_audio_transcript.done: Welcome!", direction: "Server")
        model.record("response.done", direction: "Server")
        assert(model.messages.count == 2 && model.messages[1].role == "Reachy")
        assert(model.request == "Ready for your next message")
        model.lan = true
        model.selectedAddress = "192.0.2.10"
        assert(model.endpoint == "ws://192.0.2.10:8765/v1/realtime")
        model.selectedAddress = ""
        assert(model.endpoint == "No LAN address available")
        model.consume(Data("REACHY_EVENT {\"kind\":\"disconnected\",\"id\":\"test\"}\n".utf8))
        assert(model.clients.isEmpty)
        print("Swift model checks passed")
    }
}
