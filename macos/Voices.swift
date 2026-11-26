import AVFoundation
import AppKit
import SwiftUI
import UniformTypeIdentifiers

private let previewSentence = "Hello! It is nice to meet you."

struct HostedVoice: Codable, Identifiable, Equatable {
    let id: String
    let name: String
    let type: String
}

private struct Catalog: Decodable {
    let voices: [HostedVoice]
    let default_voice: String?
    let can_transcribe: Bool
}

private struct VoiceError: LocalizedError {
    let message: String
    var errorDescription: String? { message }
}

private enum VoiceAPI {
    static func request(_ path: String, method: String = "GET",
                        fields: [String: String]? = nil, body: Data? = nil) async throws -> Data {
        let url = URL(string: "http://127.0.0.1:8765")!.appendingPathComponent(path)
        var request = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 1800)
        request.httpMethod = method
        request.httpBody = try body ?? fields.map { try JSONEncoder().encode($0) }
        if request.httpBody != nil { request.setValue("application/json", forHTTPHeaderField: "Content-Type") }
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            let detail = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["detail"]
            let validation = (detail as? [[String: Any]])?.compactMap { $0["msg"] as? String }.joined(separator: " ")
            throw VoiceError(message: (detail as? String) ?? validation ?? "The voice request failed. See Diagnostics for details.")
        }
        return data
    }
}

@MainActor
final class VoiceStudio: ObservableObject {
    @Published var voices: [HostedVoice] = []
    @Published var selected = ""
    @Published var defaultID = ""
    @Published var canTranscribe = false
    @Published var preview = previewSentence
    @Published var activity = ""
    @Published var message = ""
    private var sound: NSSound?
    private var latest: (id: String, text: String, data: Data)?
    var canSpeak: Bool { !preview.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && preview.count <= 500 }
    var current: HostedVoice? { voices.first { $0.id == selected } }

    func run(_ label: String, _ operation: @escaping @MainActor () async throws -> Void) {
        guard activity.isEmpty else { return }
        activity = label
        message = ""
        Task {
            defer { activity = "" }
            do { try await operation() }
            catch { message = error.localizedDescription }
        }
    }

    func refresh(select id: String? = nil) async throws {
        let data = try await VoiceAPI.request("v1/audio/voices")
        let catalog = try JSONDecoder().decode(Catalog.self, from: data)
        voices = catalog.voices
        defaultID = catalog.default_voice ?? ""
        canTranscribe = catalog.can_transcribe
        message = ""
        let candidate = id ?? selected
        selected = voices.contains { $0.id == candidate } ? candidate : defaultID
    }

    func play(_ data: Data) throws {
        sound?.stop()
        sound = NSSound(data: data)
        guard sound?.play() == true else { throw VoiceError(message: "Could not play the preview audio.") }
    }

    func speech() async throws -> Data {
        let id = selected, text = preview
        if let latest, latest.id == id && latest.text == text { return latest.data }
        let data = try await VoiceAPI.request("v1/audio/speech", method: "POST", fields: ["voice": id, "input": text])
        latest = (id, text, data)
        return data
    }

    func makeDefault() async throws {
        _ = try await VoiceAPI.request("local/voices/default", method: "PUT", fields: ["voice": selected])
        try await refresh()
    }

    func saved(_ data: Data) async throws {
        let voice = try JSONDecoder().decode(HostedVoice.self, from: data)
        try await refresh(select: voice.id)
    }
}

private let packageType = UTType(filenameExtension: "s2svoice") ?? .data

enum VoiceFileKind {
    case recording, package

    var types: [UTType] {
        switch self {
        case .package: return [packageType, UTType(filenameExtension: "reachyvoice") ?? .data]
        case .recording: return [.wav, .aiff, .mp3, .mpeg4Audio, UTType(filenameExtension: "flac") ?? .audio]
        }
    }

    func read(_ url: URL) throws -> Data {
        let limitMB = self == .recording ? 16 : 24
        let size = try url.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
        guard size <= limitMB * 1_048_576 else {
            throw VoiceError(message: "Choose a file of \(limitMB) MB or less.")
        }
        guard self == .recording, url.pathExtension.lowercased() == "m4a" else {
            return try Data(contentsOf: url)
        }

        // Voice Memos exports AAC or Apple Lossless. Send a WAV the server can decode.
        let input = try AVAudioFile(forReading: url)
        let format = input.processingFormat
        guard input.length > 0, Double(input.length) / format.sampleRate <= 30,
              let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(input.length)) else {
            throw VoiceError(message: "Choose a recording up to 30 seconds long.")
        }
        try input.read(into: buffer)
        let temporary = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".wav")
        defer { try? FileManager.default.removeItem(at: temporary) }
        do {
            let settings: [String: Any] = [AVFormatIDKey: kAudioFormatLinearPCM,
                AVSampleRateKey: format.sampleRate, AVNumberOfChannelsKey: format.channelCount,
                AVLinearPCMBitDepthKey: 16, AVLinearPCMIsFloatKey: false]
            let output = try AVAudioFile(forWriting: temporary, settings: settings)
            try output.write(from: buffer)
        }
        return try Data(contentsOf: temporary)
    }
}

@MainActor
private func openFile(_ kind: VoiceFileKind) throws -> (name: String, data: Data)? {
    let panel = NSOpenPanel()
    panel.allowedContentTypes = kind.types
    panel.canChooseDirectories = false
    guard panel.runModal() == .OK, let url = panel.url else { return nil }
    return (url.lastPathComponent, try kind.read(url))
}

@MainActor
private func exportURL(_ name: String, type: UTType) -> URL? {
    let panel = NSSavePanel()
    panel.nameFieldStringValue = name
    panel.allowedContentTypes = [type]
    return panel.runModal() == .OK ? panel.url : nil
}

struct VoicesView: View {
    @ObservedObject var studio: VoiceStudio
    let online: Bool
    @State private var creation: CreationMode?

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            if !online {
                ContentUnavailableView("Start the server to use voices", systemImage: "waveform")
            } else {
                HStack {
                    Text("Voice library").font(.title2.bold())
                    Spacer()
                    Button("Clone voice…") { studio.message = ""; creation = .clone }
                    Button("Design voice…") { studio.message = ""; creation = .design }
                    Button("Import…") {
                        studio.run("Importing voice…") {
                            guard let file = try openFile(.package) else { return }
                            let result = try await VoiceAPI.request("local/voices/import", method: "POST", body: file.data)
                            try await studio.saved(result)
                        }
                    }
                }
                Picker("Voice", selection: $studio.selected) {
                    if studio.voices.isEmpty { Text("No voices available").tag("") }
                    ForEach(studio.voices) { voice in
                        Text("\(voice.name) · \(voice.type.capitalized)\(voice.id == studio.defaultID ? " (default)" : "")").tag(voice.id)
                    }
                }
                if let voice = studio.current {
                    HStack {
                        Text(voice.id).font(.caption.monospaced()).foregroundStyle(.secondary).textSelection(.enabled)
                        Spacer()
                        Button("Use as server default") {
                            studio.run("Saving default…") { try await studio.makeDefault() }
                        }.disabled(voice.id == studio.defaultID)
                    }
                    Divider()
                    LabeledContent("Preview sentence") {
                        TextField("Text to speak", text: $studio.preview).textFieldStyle(.roundedBorder)
                    }
                    HStack {
                        Button("Play preview", systemImage: "play.fill") {
                            studio.run("Generating preview…") { try studio.play(await studio.speech()) }
                        }.buttonStyle(.borderedProminent).disabled(!studio.canSpeak)
                        Button("Export audio…") {
                            studio.run("Exporting audio…") {
                                guard let url = exportURL(voice.name + ".wav", type: .wav) else { return }
                                try await studio.speech().write(to: url, options: .atomic)
                            }
                        }.disabled(!studio.canSpeak)
                        if voice.type != "preset" {
                            Button("Export voice…") {
                                studio.run("Exporting voice…") {
                                    guard let url = exportURL(voice.name + ".s2svoice", type: packageType) else { return }
                                    let data = try await VoiceAPI.request("local/voices/\(voice.id)/export")
                                    try data.write(to: url, options: .atomic)
                                }
                            }
                        }
                    }
                }
                if studio.voices.isEmpty {
                    Button("Reload voices") { studio.run("Loading voices…") { try await studio.refresh() } }
                }
                VoiceStatus(studio: studio)
            }
            Spacer(minLength: 0)
        }
        .padding(18).frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(Color(nsColor: .textBackgroundColor), in: RoundedRectangle(cornerRadius: 14))
        .disabled(!studio.activity.isEmpty)
        .task(id: online) {
            guard online else { return }
            do { try await studio.refresh() } catch { if !Task.isCancelled { studio.message = error.localizedDescription } }
        }
        .sheet(item: $creation) { mode in CreateVoiceView(mode: mode, studio: studio) }
    }
}

private struct VoiceStatus: View {
    @ObservedObject var studio: VoiceStudio
    var body: some View {
        if !studio.activity.isEmpty {
            HStack { ProgressView().controlSize(.small); Text(studio.activity) }
        }
        if !studio.message.isEmpty { Text(studio.message).foregroundStyle(.red).textSelection(.enabled) }
    }
}

private enum CreationMode: String, Identifiable {
    case clone, design
    var id: String { rawValue }
}

private struct CreateVoiceView: View {
    let mode: CreationMode
    @ObservedObject var studio: VoiceStudio
    @Environment(\.dismiss) private var dismiss
    @State private var name = ""
    @State private var prompt = ""
    @State private var script = "Hello there. It is nice to meet you. What would you like to do today?"
    @State private var transcript = ""
    @State private var preview = previewSentence
    @State private var reference: Data?
    @State private var fileName = ""
    @State private var draftID = "voice_" + UUID().uuidString.lowercased().replacingOccurrences(of: "-", with: "")
    var referenceText: String { mode == .design ? script : transcript }
    var ready: Bool { reference != nil && !referenceText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text(mode == .clone ? "Clone a voice" : "Design a voice").font(.title2.bold())
            LabeledContent("Name") { TextField("Voice name", text: $name) }
            if mode == .clone {
                HStack {
                    Button("Choose recording…") {
                        studio.run(studio.canTranscribe ? "Reading and transcribing recording…" : "Reading recording…") {
                            guard let file = try openFile(.recording) else { return }
                            fileName = file.name; reference = file.data; transcript = ""
                            if studio.canTranscribe { try await transcribe(file.data) }
                        }
                    }
                    Text(fileName.isEmpty ? "M4A, WAV, AIFF, FLAC or MP3 · up to 30 seconds" : fileName)
                        .font(.caption).foregroundStyle(.secondary)
                }
                LabeledContent("Transcript") {
                    TextField("Words spoken in the recording", text: $transcript, axis: .vertical).lineLimit(2...4)
                }
                if let reference, studio.canTranscribe {
                    Button("Transcribe again") { studio.run("Transcribing…") { try await transcribe(reference) } }
                }
            } else {
                LabeledContent("Description") {
                    TextField("A warm, relaxed voice with a gentle rhythm", text: $prompt, axis: .vertical).lineLimit(2...4)
                }
                LabeledContent("Reference sentence") { TextField("Words to record", text: $script, axis: .vertical) }
                HStack {
                    Button(reference == nil ? "Generate sample" : "Generate another take") {
                        studio.run("Generating sample…") {
                            let data = try await VoiceAPI.request("local/voices/design", method: "POST",
                                                                  fields: ["prompt": prompt, "text": script])
                            reference = data
                            try studio.play(data)
                        }
                    }.disabled(prompt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || script.isEmpty)
                    if let reference {
                        Button("Replay sample") { studio.run("Playing sample…") { try studio.play(reference) } }
                    }
                }
            }
            Divider()
            LabeledContent("Preview sentence") { TextField("Text to speak", text: $preview, axis: .vertical) }
            Button("Play voice preview", systemImage: "play.fill") {
                studio.run("Generating preview…") {
                    guard let reference else { return }
                    let fields = ["audio": reference.base64EncodedString(), "transcript": referenceText, "text": preview]
                    try studio.play(await VoiceAPI.request("local/voices/preview", method: "POST", fields: fields))
                }
            }.disabled(!ready || preview.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            Text("The first generation downloads the required voice model.").font(.caption).foregroundStyle(.secondary)
            VoiceStatus(studio: studio)
            HStack {
                Spacer()
                Button("Cancel") { studio.message = ""; dismiss() }.keyboardShortcut(.cancelAction)
                Button("Save voice") {
                    studio.run("Saving voice…") {
                        guard let reference else { return }
                        var fields = ["id": draftID, "name": name, "audio": reference.base64EncodedString(),
                                      "transcript": referenceText, "type": mode == .clone ? "cloned" : "designed"]
                        if mode == .design { fields["prompt"] = prompt }
                        let data = try await VoiceAPI.request("local/voices", method: "POST", fields: fields)
                        try await studio.saved(data)
                        dismiss()
                    }
                }.buttonStyle(.borderedProminent).disabled(!ready || name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }.textFieldStyle(.roundedBorder).padding(24).frame(width: 550)
            .disabled(!studio.activity.isEmpty).interactiveDismissDisabled(!studio.activity.isEmpty)
            .onChange(of: prompt) { _, _ in reference = nil }
            .onChange(of: script) { _, _ in reference = nil }
    }

    private func transcribe(_ audio: Data) async throws {
        let data = try await VoiceAPI.request("local/voices/transcribe", method: "POST", fields: ["audio": audio.base64EncodedString()])
        transcript = try JSONDecoder().decode([String: String].self, from: data)["transcript"] ?? ""
    }
}
