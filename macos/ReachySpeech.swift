import AppKit
import SwiftUI
import Darwin
#if SPARKLE_UPDATES
import Sparkle
#endif

struct ConversationEntry: Identifiable {
    let id = UUID()
    let role: String
    let text: String
    let time = Date()
}

final class ServerModel: ObservableObject {
    @Published var status = "Stopped"
    @Published var running = false
    @Published var lan = false
    @Published var clients: [String: String] = [:]
    @Published var logs = ""
    @Published var request = "Waiting for a conversation"
    @Published var messages: [ConversationEntry] = []
    @Published var addresses: [String] = []
    @Published var selectedAddress = ""
    var endpoint: String {
        let host = lan ? selectedAddress : "127.0.0.1"
        return host.isEmpty ? "No LAN address available" : "ws://\(host):8765/v1/realtime"
    }
    var busy: Bool { running && status != "Running" }
    var failed: Bool { status.hasPrefix("Failed") }
    func refreshAddresses() {
        var interfaces: UnsafeMutablePointer<ifaddrs>?
        var found: [String] = []
        if getifaddrs(&interfaces) == 0 {
            defer { freeifaddrs(interfaces) }
            var cursor = interfaces
            while let item = cursor {
                defer { cursor = item.pointee.ifa_next }
                guard let address = item.pointee.ifa_addr,
                      address.pointee.sa_family == UInt8(AF_INET),
                      String(cString: item.pointee.ifa_name).hasPrefix("en"),
                      (item.pointee.ifa_flags & UInt32(IFF_UP)) != 0 else { continue }
                var host = [CChar](repeating: 0, count: Int(NI_MAXHOST))
                if getnameinfo(address, socklen_t(address.pointee.sa_len), &host,
                               socklen_t(host.count), nil, 0, NI_NUMERICHOST) == 0 {
                    found.append(String(cString: host))
                }
            }
        }
        addresses = Array(Set(found)).sorted()
        if !addresses.contains(selectedAddress) { selectedAddress = addresses.first ?? "" }
    }
    func record(_ text: String, direction: String) {
        let parts = text.components(separatedBy: ": ")
        let kind = parts[0]
        let content = parts.dropFirst().joined(separator: ": ")
        let user = kind == "conversation.item.create" && direction == "Client"
            || kind == "conversation.item.input_audio_transcription.completed"
        let assistant = kind == "response.audio_transcript.done"
            || kind == "response.output_audio_transcript.done" || kind == "response.text.done"
            || kind == "response.output_text.done"
        if (user || assistant) && !content.isEmpty {
            messages.append(ConversationEntry(role: user ? "You" : "Reachy", text: content))
            if messages.count > 200 { messages.removeFirst(messages.count - 200) }
        }
        switch kind {
        case "input_audio_buffer.speech_started": request = "Listening"
        case "input_audio_buffer.speech_stopped", "response.created": request = "Thinking"
        case "response.output_audio_transcript.delta", "response.audio_transcript.delta": request = "Speaking"
        case "response.done": request = "Ready for your next message"
        case "error": request = "Request failed — see diagnostics"
        default: break
        }
    }
    private var process: Process?
    private var pending = Data()
    private var stopping = false
    private var pipe: Pipe?

    func append(_ line: String) {
        logs += line + "\n"
        if logs.count > 100_000 { logs = String(logs.suffix(80_000)) }
    }
    func consume(_ data: Data) {
        pending.append(data)
        while let end = pending.firstIndex(of: 10) {
            let line = String(decoding: pending[..<end], as: UTF8.self)
            pending.removeSubrange(...end)
            if line.hasPrefix("REACHY_EVENT "),
               let json = line.dropFirst(13).data(using: .utf8),
               let event = try? JSONSerialization.jsonObject(with: json) as? [String: String] {
                let id = event["id"] ?? ""
                switch event["kind"] {
                case "connected": clients[id] = event["peer"] ?? "Unknown"
                case "disconnected": clients.removeValue(forKey: id)
                case "status": if !stopping { status = event["text"] ?? "Preparing" }
                case "message":
                    let text = event["text"] ?? ""
                    record(text, direction: event["direction"] ?? "")
                    append("[\(id)] \(event["direction"] ?? ""): \(text)")
                default: break
                }
            } else {
                append(line)
                if line.contains("Uvicorn running on"), !stopping { status = "Running" }
            }
        }
        // Bound malformed or carriage-return-only download output.
        if pending.count > 32_768 {
            append(String(decoding: pending, as: UTF8.self)); pending.removeAll()
        }
    }
    func start(prepareOnly: Bool = false) {
        guard process == nil else { return }
        let p = Process()
        let output = Pipe()
        guard let executable = Bundle.main.executableURL,
              let resources = Bundle.main.resourceURL else { return }
        p.executableURL = executable
        p.arguments = ["--worker", resources.appendingPathComponent("bootstrap.sh").path, resources.path]
            + (prepareOnly ? ["--prepare-only"] : (lan ? ["--lan"] : []))
        p.standardOutput = output; p.standardError = output
        p.standardInput = FileHandle.nullDevice
        pending.removeAll(); stopping = false
        refreshAddresses()
        request = "Waiting for a conversation"
        status = prepareOnly ? "Setting up" : "Starting"
        running = true; clients.removeAll()
        pipe = output; process = p
        output.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            if data.isEmpty { handle.readabilityHandler = nil; return }
            DispatchQueue.main.async { self?.consume(data) }
        }
        p.terminationHandler = { [weak self] child in
            DispatchQueue.main.async {
                guard let self = self else { return }
                // Kill any surviving descendants, including interrupted setup downloads.
                kill(-child.processIdentifier, SIGKILL)
                self.status = self.stopping ? "Stopped" : (child.terminationStatus == 0 ? (prepareOnly ? "Ready" : "Stopped") : "Failed — see logs")
                self.append("Process exited (\(child.terminationStatus)).")
                self.request = "Server is stopped"
                self.clients.removeAll(); self.running = false; self.process = nil; self.pipe = nil
            }
        }
        do { try p.run() }
        catch {
            output.fileHandleForReading.readabilityHandler = nil
            append(error.localizedDescription); status = "Failed — see logs"
            process = nil; pipe = nil; running = false
        }
    }
    func stop() {
        guard let p = process, p.isRunning else { return }
        stopping = true; status = "Stopping"
        kill(-p.processIdentifier, SIGTERM)
        DispatchQueue.main.asyncAfter(deadline: .now() + 5) { [weak self, weak p] in
            guard let p = p, p.isRunning, self?.process === p else { return }
            kill(-p.processIdentifier, SIGKILL)
        }
    }
    func shutdown() {
        guard let p = process, p.isRunning else { return }
        kill(-p.processIdentifier, SIGKILL)
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    var model: ServerModel?
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
    func applicationWillTerminate(_ notification: Notification) { model?.shutdown() }
}

struct ContentView: View {
    @ObservedObject var model: ServerModel
    @State private var tab = "Conversation"
    @State private var search = ""
    @State private var follow = true
    @State private var copied = false
    private let accent = Color(red: 0.02, green: 0.52, blue: 0.53)
    var filteredLogs: String {
        search.isEmpty ? model.logs : model.logs.components(separatedBy: "\n")
            .filter { $0.localizedCaseInsensitiveContains(search) }.joined(separator: "\n")
    }
    var body: some View {
        HStack(spacing: 0) {
            sidebar.frame(width: 260)
            Divider()
            VStack(alignment: .leading, spacing: 20) {
                HStack(alignment: .top) {
                    VStack(alignment: .leading, spacing: 6) {
                        Text("Speech2SpeechModelHoster").font(.largeTitle.bold())
                        Text("Host the speech models on this Mac and connect the Reachy Mini Conversation App.")
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    HStack(spacing: 7) {
                        Circle().fill(model.failed ? Color.red : model.status == "Running" ? accent : Color.secondary)
                            .frame(width: 7, height: 7)
                        Text(model.status == "Running" ? "Server online" : model.failed ? "Needs attention" : model.running ? "Preparing" : "Server offline")
                            .font(.callout.weight(.medium))
                    }.padding(.horizontal, 12).padding(.vertical, 8)
                        .background(accent.opacity(0.08), in: Capsule())
                }
                if model.busy || model.failed {
                    HStack(spacing: 12) {
                        if model.busy { ProgressView().controlSize(.small) }
                        else { Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(.orange) }
                        VStack(alignment: .leading, spacing: 3) {
                            Text(model.status).font(.callout.weight(.semibold)).lineLimit(2)
                            Text(model.failed ? "Review diagnostics, then retry Start server." : "First setup can take several minutes. Downloads are reused on later launches.")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                        Spacer()
                        Button("Show diagnostics") { tab = "Diagnostics" }
                    }.padding(14).background(accent.opacity(0.07), in: RoundedRectangle(cornerRadius: 12))
                }
                HStack {
                    Image(systemName: model.request == "Listening" ? "waveform" : "bubble.left.and.bubble.right")
                        .foregroundStyle(accent)
                    Text(model.status == "Running" ? model.request : "Start the server to begin a conversation")
                        .font(.callout)
                    Spacer()
                    Text("\(model.messages.count) messages").font(.caption).foregroundStyle(.secondary)
                }
                HStack {
                    Picker("View", selection: $tab) {
                        Text("Conversation").tag("Conversation")
                        Text("Diagnostics").tag("Diagnostics")
                    }.pickerStyle(.segmented).labelsHidden().frame(width: 260)
                    Spacer()
                    Toggle("Follow latest", isOn: $follow).toggleStyle(.checkbox).font(.caption)
                    Button("Clear", systemImage: "trash") {
                        if tab == "Conversation" { model.messages.removeAll() } else { model.logs = "" }
                    }.help("Clear the current view")
                }
                if tab == "Conversation" { conversation } else { diagnostics }
                HStack(spacing: 6) {
                    Image(systemName: "lock.shield")
                    Text("Processed on this Mac · History stays in memory")
                    Spacer()
                    Text("One conversation at a time")
                }.font(.caption).foregroundStyle(.secondary)
            }.padding(28).frame(maxWidth: .infinity, maxHeight: .infinity)
        }.frame(minWidth: 1000, minHeight: 690)
            .background(Color(nsColor: .windowBackgroundColor)).tint(accent)
            .onAppear { model.refreshAddresses() }
    }
    private var sidebar: some View {
        VStack(alignment: .leading, spacing: 24) {
            HStack(spacing: 10) {
                if let url = Bundle.main.url(forResource: "AppIcon", withExtension: "png"),
                   let image = NSImage(contentsOf: url) {
                    Image(nsImage: image).resizable().scaledToFit().frame(width: 48, height: 48)
                }
                VStack(alignment: .leading, spacing: 3) {
                    Text("Reachy Mini").font(.headline)
                    Text("LOCAL SPEECH").font(.system(size: 10, weight: .semibold, design: .rounded))
                        .tracking(1.8).foregroundStyle(.secondary)
                }
            }
            VStack(alignment: .leading, spacing: 12) {
                Text("SERVER").font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                Button { model.running ? model.stop() : model.start() } label: {
                    Label(model.running ? (model.status == "Running" ? "Stop server" : "Cancel") : model.failed ? "Retry start" : "Start server",
                          systemImage: model.running ? "stop.fill" : "play.fill")
                        .frame(maxWidth: .infinity).padding(.vertical, 5)
                }.buttonStyle(.borderedProminent).controlSize(.large)
                    .disabled(model.status == "Stopping")
                Picker("Access", selection: $model.lan) {
                    Text("This Mac").tag(false)
                    Text("Local network").tag(true)
                }.pickerStyle(.segmented).labelsHidden().disabled(model.running)
                Text(model.lan ? "Connect Reachy Wireless on the same trusted network." : "For a conversation app running on this Mac.")
                    .font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                if model.lan && model.addresses.count > 1 {
                    Picker("Mac address", selection: $model.selectedAddress) {
                        ForEach(model.addresses, id: \.self) { Text($0).tag($0) }
                    }
                }
                VStack(alignment: .leading, spacing: 10) {
                    Text("CONNECTION URL").font(.system(size: 10, weight: .semibold)).foregroundStyle(.secondary)
                    Text(model.endpoint).font(.system(size: 11, design: .monospaced))
                        .textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
                    HStack {
                        Button(copied ? "Copied" : "Copy URL", systemImage: copied ? "checkmark" : "doc.on.doc") {
                            NSPasteboard.general.clearContents()
                            NSPasteboard.general.setString(model.endpoint, forType: .string)
                            copied = true
                            DispatchQueue.main.asyncAfter(deadline: .now() + 2) { copied = false }
                        }.disabled(model.lan && model.selectedAddress.isEmpty)
                        Spacer()
                        Button { model.refreshAddresses() } label: { Image(systemName: "arrow.clockwise") }
                            .help("Refresh network addresses").accessibilityLabel("Refresh network addresses")
                    }.buttonStyle(.borderless).font(.caption)
                }.padding(12).background(Color(nsColor: .textBackgroundColor), in: RoundedRectangle(cornerRadius: 10))
            }
            Divider()
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    Text("CLIENTS").font(.caption.weight(.semibold))
                    Spacer()
                    Text("\(model.clients.count)").font(.caption.monospacedDigit())
                }.foregroundStyle(.secondary)
                if model.clients.isEmpty {
                    Label("No clients connected", systemImage: "antenna.radiowaves.left.and.right")
                        .font(.callout).foregroundStyle(.secondary)
                    Text("Connected apps will appear here.").font(.caption).foregroundStyle(.tertiary)
                }
                ForEach(model.clients.keys.sorted(), id: \.self) { key in
                    HStack(alignment: .top, spacing: 8) {
                        Circle().fill(accent).frame(width: 7, height: 7).padding(.top, 5)
                        VStack(alignment: .leading, spacing: 4) {
                            Text(model.clients[key] ?? "").font(.caption.monospaced()).textSelection(.enabled)
                            Text("Session \(key)").font(.system(size: 10)).foregroundStyle(.secondary)
                        }
                    }
                }
            }
            Spacer()
            VStack(alignment: .leading, spacing: 6) {
                Label("Models pinned", systemImage: "checkmark.seal").font(.caption.weight(.medium))
                Text("Parakeet · Qwen · Qwen TTS").font(.caption).foregroundStyle(.secondary)
                Text("First setup needs internet and 15 GB free space.")
                    .font(.caption).foregroundStyle(.tertiary).fixedSize(horizontal: false, vertical: true)
            }
        }.padding(22).frame(maxHeight: .infinity)
            .background(Color(nsColor: .controlBackgroundColor).opacity(0.55))
    }
    private var conversation: some View {
        ScrollViewReader { proxy in
            ScrollView {
                if model.messages.isEmpty {
                    VStack(spacing: 14) {
                        Image(systemName: "bubble.left.and.bubble.right").font(.system(size: 36, weight: .light)).foregroundStyle(accent)
                        Text("A place for your conversation").font(.title3.weight(.semibold))
                        Text("Start the server, then connect the Reachy conversation app.\nYour words and Reachy’s replies will appear here.")
                            .multilineTextAlignment(.center).font(.callout).foregroundStyle(.secondary)
                    }.frame(maxWidth: .infinity).padding(.vertical, 80)
                } else {
                    LazyVStack(alignment: .leading, spacing: 18) {
                        ForEach(model.messages) { entry in
                            VStack(alignment: .leading, spacing: 8) {
                                HStack {
                                    Label(entry.role, systemImage: entry.role == "You" ? "person.crop.circle" : "waveform.circle")
                                        .font(.callout.weight(.semibold)).foregroundStyle(entry.role == "You" ? Color.primary : accent)
                                    Spacer()
                                    Text(entry.time, style: .time).font(.caption).foregroundStyle(.tertiary)
                                }
                                Text(entry.text).font(.body).lineSpacing(5).textSelection(.enabled)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                            }.padding(16)
                                .background(entry.role == "You" ? Color(nsColor: .controlBackgroundColor) : accent.opacity(0.07), in: RoundedRectangle(cornerRadius: 12))
                        }
                    }.padding(18)
                }
                Color.clear.frame(height: 1).id("end")
            }.background(Color(nsColor: .textBackgroundColor), in: RoundedRectangle(cornerRadius: 14))
                .onChange(of: model.messages.count) { _, _ in if follow { proxy.scrollTo("end", anchor: .bottom) } }
        }
    }
    private var diagnostics: some View {
        VStack(spacing: 10) {
            TextField("Filter diagnostics…", text: $search).textFieldStyle(.roundedBorder)
            ScrollViewReader { proxy in
                ScrollView {
                    Text(filteredLogs.isEmpty ? "No matching diagnostics." : filteredLogs)
                        .font(.system(size: 11, design: .monospaced)).textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    Color.clear.frame(height: 1).id("end")
                }.padding(14).background(Color(nsColor: .textBackgroundColor), in: RoundedRectangle(cornerRadius: 12))
                    .onChange(of: model.logs) { _, _ in if follow { proxy.scrollTo("end", anchor: .bottom) } }
            }
        }
    }
}

#if !MODEL_TEST
#if SPARKLE_UPDATES
@MainActor
private final class AppUpdates: ObservableObject {
    let controller = SPUStandardUpdaterController(
        startingUpdater: true, updaterDelegate: nil, userDriverDelegate: nil
    )
    @Published var canCheck = false

    init() {
        controller.updater.publisher(for: \.canCheckForUpdates).assign(to: &$canCheck)
    }
}
#endif

@main
struct ReachySpeechApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var delegate
    @StateObject private var model = ServerModel()
    #if SPARKLE_UPDATES
    @ObservedObject private var updates: AppUpdates
    #endif
    init() {
        if CommandLine.arguments.dropFirst().first == "--worker" {
            if getpgrp() != getpid() && setpgid(0, 0) != 0 {
                fputs("Unable to isolate worker process group\n", stderr); exit(1)
            }
            let arguments = ["/bin/bash"] + Array(CommandLine.arguments.dropFirst(2))
            let pointers = arguments.map { strdup($0) } + [nil]
            pointers.withUnsafeBufferPointer { buffer in _ = execv("/bin/bash", buffer.baseAddress!) }
            exit(1)
        }
        #if SPARKLE_UPDATES
        updates = AppUpdates()
        #endif
    }
    var body: some Scene {
        Window("Reachy Mini Speech", id: "main") {
            ContentView(model: model).onAppear {
                delegate.model = model
                // Prepare on first launch; listening still requires Start.
                let home = ProcessInfo.processInfo.environment["REACHY_APP_HOME"] ?? (NSHomeDirectory() + "/Library/Application Support/Reachy Mini Speech")
                if !FileManager.default.fileExists(atPath: home + "/desktop-profile.yaml") {
                    model.start(prepareOnly: true)
                }
            }
        }.commands {
            CommandGroup(replacing: .newItem) {}
            #if SPARKLE_UPDATES
            CommandGroup(after: .appInfo) {
                Button("Check for Updates…") { updates.controller.checkForUpdates(nil) }
                    .disabled(!updates.canCheck)
            }
            #endif
        }
    }
}

#endif
