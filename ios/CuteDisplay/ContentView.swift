import SwiftUI
import Foundation
import Security

private enum CuteAISecret {
    static let service = "CuteDisplay.OpenWebUI"
    static func load() -> String {
        let q: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service, kSecAttrAccount as String: "api-key",
            kSecReturnData as String: true, kSecMatchLimit as String: kSecMatchLimitOne]
        var result: CFTypeRef?
        guard SecItemCopyMatching(q as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data else { return "" }
        return String(data: data, encoding: .utf8) ?? ""
    }
    static func save(_ value: String) {
        let q: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service, kSecAttrAccount as String: "api-key"]
        SecItemDelete(q as CFDictionary)
        guard !value.isEmpty else { return }
        var insert = q
        insert[kSecValueData as String] = Data(value.utf8)
        insert[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        SecItemAdd(insert as CFDictionary, nil)
    }
}

enum CuteMood: Int, CaseIterable, Identifiable {
    case neutral = 0, happy, sad, angry, hungry, sleepy, excited, shy
    var id: Int { rawValue }
    var title: String { String(describing: self).capitalized }
    var symbol: String {
        switch self {
        case .neutral: return "😐"
        case .happy: return "😊"
        case .sad: return "😢"
        case .angry: return "😠"
        case .hungry: return "😋"
        case .sleepy: return "😴"
        case .excited: return "🤩"
        case .shy: return "🥹"
        }
    }
}

enum CuteCharacter: Int, CaseIterable, Identifiable {
    case bunny = 0, kitty, chiikawa, bear, panda, fox
    var id: Int { rawValue }
    var title: String {
        switch self {
        case .bunny: return "Bunny"
        case .kitty: return "Hello Kitty"
        case .chiikawa: return "Chiikawa"
        case .bear: return "Teddy Bear"
        case .panda: return "Panda"
        case .fox: return "Little Fox"
        }
    }
    var symbol: String {
        switch self {
        case .bunny: return "🐰"
        case .kitty: return "🎀"
        case .chiikawa: return "🤍"
        case .bear: return "🧸"
        case .panda: return "🐼"
        case .fox: return "🦊"
        }
    }
}

struct CuteDisplayProfile: Codable, Identifiable {
    var id: UUID = UUID()
    var name: String
    var message: String
    var theme: Int
    var character: Int
    var mood: Int
    var visible: Bool
    var mascotSize: Int
    var accessory: Int
    var objectMode: Int
    var heldObject: Int
    var frequency: Int
    var intensity: Int
    var personality: Bool
    var fontSize: Int
    var bubble: Bool
    var typewriter: Bool
    var brightness: Double
}

struct ContentView: View {
    // Keep raw BLE time estimates in minutes; format only when displayed.
    private func batteryTimeText(_ minutes: Int) -> String {
        guard minutes > 0 && minutes < 65535 && minutes <= 10080 else { return "—" }
        let hours = minutes / 60
        let remainder = minutes % 60
        return "\(hours) hours \(remainder) min"
    }

    // Avoid optional.map closures in SwiftUI result-builder expressions.
    private func displayedBatteryTime(_ minutes: Int?, when state: String) -> String {
        guard batteryStateText == state, let minutes = minutes else { return "—" }
        return batteryTimeText(minutes)
    }

    @StateObject private var bluetooth = BluetoothManager()
    @State private var message = UserDefaults.standard.string(forKey: "savedMessage") ?? "こんにちわ"
    @State private var brightness = 75.0
    @State private var audioTestPhase = "Ready"
    @State private var audioTestRunning = false
    @State private var micGain = UserDefaults.standard.object(forKey: "cuteMicGain") as? Double ?? 150
    @State private var speakerVolume = UserDefaults.standard.object(forKey: "cuteSpeakerVolume") as? Double ?? 65
    @State private var clockTimezone = UserDefaults.standard.integer(forKey: "cuteClockZone")
    private let clockZones = ["Japan (JST)", "UTC", "Central Europe (CET/CEST)",
                              "US Eastern", "US Pacific", "United Kingdom", "Australia Sydney"]
    @State private var aiServer = UserDefaults.standard.string(forKey: "cuteAIServer") ?? ""
    @State private var aiModel = UserDefaults.standard.string(forKey: "cuteAIModel") ?? "cutedisplay-ai"
    @State private var aiAPIKey = CuteAISecret.load()
    @State private var aiQuestion = ""
    @State private var lastSubmittedAIQuestion = ""
    @State private var aiResponse = ""
    @State private var aiStatus = "Not configured"
    @State private var aiBusy = false
    @State private var aiDisplayTask: Task<Void, Never>?
    @State private var aiSendToKitty = true
    @State private var wifiName = UserDefaults.standard.string(forKey: "cuteWiFiName") ?? ""
    @State private var wifiPassword = ""
    @State private var showingIPSettings = false
    @State private var wifiDHCPSelection = true
    @State private var staticIP = ""
    @State private var staticMask = "255.255.255.0"
    @State private var staticGateway = ""
    @State private var staticDNS = ""
    @State private var showWiFiPassword = false
    // Settings apply directly; the redundant preview-before-sending mode was removed.
    private let previewOnly = false
    @State private var selectedPage = 0
    @State private var displayProfiles: [CuteDisplayProfile] = {
        guard let d=UserDefaults.standard.data(forKey: "cuteSavedProfiles"),
              let v=try? JSONDecoder().decode([CuteDisplayProfile].self,from:d) else { return [] }
        return v
    }()
    @State private var newProfileName = ""
    @State private var lastAppliedScheduledBrightness: Int?
    @State private var autoBrightness = UserDefaults.standard.bool(forKey: "cuteAutoBrightness")
    @State private var dayStart = UserDefaults.standard.object(forKey: "cuteDayStart") as? Int ?? 8
    @State private var nightStart = UserDefaults.standard.object(forKey: "cuteNightStart") as? Int ?? 22
    @State private var dayBrightness = UserDefaults.standard.object(forKey: "cuteDayBrightness") as? Double ?? 80
    @State private var nightBrightness = UserDefaults.standard.object(forKey: "cuteNightBrightness") as? Double ?? 25
    @State private var selectedCharacter = CuteCharacter(
        rawValue: UserDefaults.standard.object(forKey: "selectedCharacter") as? Int ?? 1
    ) ?? .kitty
    @State private var showMascot = UserDefaults.standard.object(forKey: "showMascot") as? Bool ?? true
    @State private var selectedMood = CuteMood(rawValue: UserDefaults.standard.integer(forKey: "mascotMood")) ?? .happy
    @State private var accessoryStyle = UserDefaults.standard.integer(forKey: "cuteAccessoryStyle")
    @State private var heldObjectMode = UserDefaults.standard.integer(forKey: "cuteHeldObjectMode")
    @State private var heldObject = UserDefaults.standard.integer(forKey: "cuteHeldObject")
    @State private var animationFrequency = UserDefaults.standard.object(forKey: "cuteAnimationFrequency") as? Int ?? 1
    @State private var animationIntensity = UserDefaults.standard.object(forKey: "cuteAnimationIntensity") as? Int ?? 1
    @State private var personalityAnimations = UserDefaults.standard.object(forKey: "cutePersonalityAnimations") as? Bool ?? true
    private let accessoryNames = ["None", "Glasses", "Ribbon", "Crown", "Scarf", "Party Hat", "Flower", "Seasonal"]
    private let objectNames = ["None", "Heart", "Flowers", "Cupcake", "Pillow", "Wand", "Tissue", "Cloud"]
    @State private var surpriseAnimationsEnabled = UserDefaults.standard.object(forKey: "surpriseAnimationsEnabled") as? Bool ?? true
    @State private var mascotSize = UserDefaults.standard.object(forKey: "mascotSize") as? Int ?? 100
    @State private var messageFontSize = UserDefaults.standard.object(forKey: "messageFontSize") as? Int ?? 3
    @State private var speechBubbleEnabled = UserDefaults.standard.bool(forKey: "speechBubbleEnabled")
    @State private var speechTypewriter = UserDefaults.standard.object(forKey: "speechTypewriter") as? Bool ?? true
    @State private var selectedTheme = UserDefaults.standard.integer(forKey: "displayTheme")
    private let themeNames = [
        "Pink", "Cyan", "Mint", "Yellow", "Lavender",
        "Rose", "Ocean", "Peach", "Lime", "Ruby",
        "Ice", "Sunset", "Lilac", "Gold", "Sky",
        "Coral", "Turquoise", "Emerald", "Violet", "Magenta", "Amber", "Periwinkle", "Pearl", "Crimson", "Neon"
    ]
    private let themeColors: [Color] = [
        Color(red: 1, green: 0.35, blue: 0.75),
        Color(red: 0, green: 1, blue: 1), Color(red: 0, green: 1, blue: 0),
        Color(red: 1, green: 1, blue: 0), Color(red: 0.5, green: 0, blue: 0.5),
        Color(red: 1, green: 0.48, blue: 0.62), Color(red: 0, green: 0, blue: 1),
        Color(red: 1, green: 0.70, blue: 0.47), Color(red: 0, green: 1, blue: 0), Color(red: 1, green: 0, blue: 0),
        Color(red: 0.73, green: 0.95, blue: 1), Color(red: 1, green: 0.5, blue: 0),
        Color(red: 0.82, green: 0.51, blue: 1),
        Color(red: 1, green: 0.80, blue: 0.28),
        Color(red: 0.36, green: 0.75, blue: 1),
        Color(red: 1.0000, green: 0.4275, blue: 0.3961),
        Color(red: 0.2118, green: 0.8980, blue: 0.8196),
        Color(red: 0.1765, green: 0.9020, blue: 0.5451),
        Color(red: 0.5725, green: 0.3608, blue: 1.0000),
        Color(red: 1.0000, green: 0.2588, blue: 0.9294),
        Color(red: 1.0000, green: 0.6863, blue: 0.1961),
        Color(red: 0.5137, green: 0.5843, blue: 1.0000),
        Color(red: 0.9451, green: 0.9137, blue: 1.0000),
        Color(red: 0.9294, green: 0.1882, blue: 0.3333),
        Color(red: 0.5725, green: 1.0000, blue: 0.2549)
    ]
    private var themeColor: Color { themeColors[min(24, max(0, selectedTheme))] }
    // LCD background is always black in both modes.
    private var lcdBackground: Color { .black }
    private var lcdMascotBackground: Color { .black }
    private var mascotPreviewWidth: CGFloat { showMascot ? CGFloat(max(40, 98 * mascotSize / 100)) * 0.9 : 0 }
    @State private var appNotice = ""
    @State private var showingPowerConfirmation = false

    private let quickMessages = ["こんにちは！", "Hello!", "How are you?", "I am CuteDisplay!", "Let’s chat!", "今日もよろしくね！"]

    private var shouldAutoSend: Bool { canSend && !previewOnly }
    private func updateScheduledBrightness() {
        guard autoBrightness, bluetooth.isConnected, !previewOnly else { return }
        let hour = Calendar.current.component(.hour, from: Date())
        let isDay = dayStart < nightStart ? (hour >= dayStart && hour < nightStart) :
            (hour >= dayStart || hour < nightStart)
        let amount = Int(isDay ? dayBrightness : nightBrightness)
        guard lastAppliedScheduledBrightness != amount else { return }
        brightness = Double(amount)
        lastAppliedScheduledBrightness = amount
        bluetooth.setBrightness(amount)
    }
    private var canSend: Bool { bluetooth.isSimulator || bluetooth.isConnected }
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 16) {
                    deviceStatusSection
                    Picker("Controls", selection: $selectedPage) {
                        Text("Home").tag(0)
                        Text("Kitty").tag(1)
                        Text("Settings").tag(2)
                    }
                    .pickerStyle(.segmented)
                    .accessibilityLabel("CuteDisplay sections")

                    switch selectedPage {
                    case 0:
                        messageSection
                        aiSection
                        displayPreview
                    case 1:
                        characterSection
                        moodSection
                        mascotCustomizationSection
                        appearanceSection
                        themeSection
                    default:
                        wifiSection
                        brightnessSection
                        displayProfilesSection
                        powerSection
                    }
                    if !appNotice.isEmpty {
                        Text(appNotice)
                            .font(.caption)
                            .foregroundStyle(.yellow)
                            .multilineTextAlignment(.center)
                    }
                }
                .padding()
            }
            .background(Color(red: 0.06, green: 0.07, blue: 0.12))
            .navigationTitle("CuteDisplay")
            .preferredColorScheme(.dark)
            .confirmationDialog(
                "Turn CuteDisplay off?",
                isPresented: $showingPowerConfirmation,
                titleVisibility: .visible
            ) {
                Button("Turn Display Off", role: .destructive) {
                    bluetooth.powerOff()
                    appNotice = "Device entering deep sleep. Press the LILYGO RESET button to wake it."
                }
                Button("Cancel", role: .cancel) { }
            } message: {
                Text("This turns off the LCD and puts the ESP32 into low-power deep sleep. Bluetooth disconnects. Press the hardware RESET button to restart.")
            }
        }
        .onChange(of: bluetooth.isConnected) { _, connected in
            // Connecting/reconnecting must never overwrite the running LCD display.
            // Battery telemetry is recovered by BluetoothManager independently.
            if !connected { lastAppliedScheduledBrightness = nil }
            else { updateScheduledBrightness() }
        }
        .onChange(of: message) { _, value in
            UserDefaults.standard.set(value, forKey: "savedMessage")
        }
        .task {
            while !Task.isCancelled {
                updateScheduledBrightness()
                try? await Task.sleep(for: .seconds(60))
            }
        }
    }

    // MARK: - Wi-Fi setup and telemetry
    private var brainWiFiSummary: String {
        if !bluetooth.isConnected { return "Connect Bluetooth to check Wi-Fi" }
        if bluetooth.wifiConnected { return "Brain Wi-Fi connected" }
        switch bluetooth.wifiConnectionState {
        case "CONNECTING": return "Brain connecting to Wi-Fi..."
        case "RETRYING": return "Brain retrying Wi-Fi..."
        case "CONFIGURING": return "Sending Wi-Fi settings..."
        case "OFF": return "Brain Wi-Fi off"
        default: return "Brain Wi-Fi disconnected"
        }
    }

    private var wifiSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            sectionTitle("S3 BRAIN — WI-FI & IP")
            Picker("Kitty clock timezone", selection: $clockTimezone) {
                ForEach(0..<clockZones.count, id: \.self) { index in
                    Text(clockZones[index]).tag(index)
                }
            }
            .onChange(of: clockTimezone) { _, newValue in
                UserDefaults.standard.set(newValue, forKey: "cuteClockZone")
                if bluetooth.bluetoothBrainConnected {
                    bluetooth.sendControlCommand("TIME:ZONE:\(newValue)")
                }
            }
            Button("Apply clock timezone to S3") {
                bluetooth.sendControlCommand("TIME:ZONE:\(clockTimezone)")
            }
            .disabled(!bluetooth.bluetoothBrainConnected)
            HStack(spacing: 8) {
                Image(systemName: bluetooth.wifiConnected ? "wifi" : "wifi.slash")
                    .foregroundStyle(bluetooth.wifiConnected ? .green : .orange)
                Text(brainWiFiSummary)
                    .font(.subheadline.bold())
                Spacer()
            }
            if bluetooth.isConnected && !bluetooth.wifiConnectionError.isEmpty {
                Label(bluetooth.wifiConnectionError, systemImage: "exclamationmark.triangle")
                    .font(.caption)
                    .foregroundStyle(.orange)
            }
            HStack {
                Text("Brain Wi-Fi state: \(bluetooth.wifiConnectionState)")
                    .font(.caption2).foregroundStyle(.secondary)
                Spacer()
                if bluetooth.wifiConnected {
                    Text("IP: \(bluetooth.wifiIP)")
                        .font(.caption2).foregroundStyle(.secondary)
                }
            }
            TextField("Wi-Fi network (SSID)", text: $wifiName)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .textFieldStyle(.roundedBorder)
            HStack {
                Group {
                    if showWiFiPassword {
                        TextField("Wi-Fi password", text: $wifiPassword)
                    } else {
                        SecureField("Wi-Fi password", text: $wifiPassword)
                    }
                }
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                Button {
                    showWiFiPassword.toggle()
                } label: {
                    Image(systemName: showWiFiPassword ? "eye.slash" : "eye")
                }
                .accessibilityLabel(showWiFiPassword ? "Hide password" : "Show password")
            }
            .textFieldStyle(.roundedBorder)
            Button("Connect S3 Brain to Wi-Fi") {
                UserDefaults.standard.set(wifiName, forKey: "cuteWiFiName")
                bluetooth.connectWiFi(ssid: wifiName, password: wifiPassword)
                wifiPassword = ""
            }
            .buttonStyle(.borderedProminent)
            .disabled(!bluetooth.bluetoothBrainConnected || wifiName.isEmpty)
            HStack(spacing: 8) {
                Button("Reconnect") { bluetooth.enableWiFi() }
                Button("Disconnect") { bluetooth.disconnectWiFi() }
                Button("Forget", role: .destructive) {
                    bluetooth.forgetWiFi()
                    wifiPassword = ""
                }
            }
            .buttonStyle(.bordered)
            .disabled(!bluetooth.bluetoothBrainConnected)
            Divider()
            HStack {
                Button("IP Settings") {
                    wifiDHCPSelection = bluetooth.wifiDHCP
                    showingIPSettings = true
                }

            }
            .buttonStyle(.bordered)
            .disabled(!bluetooth.bluetoothBrainConnected)
            Text("The ESP32-S3 connects to 2.4 GHz Wi-Fi only. The LILYGO's own Wi-Fi is disabled; its left-button long press toggles Brain Wi-Fi.")
                .font(.caption2).foregroundStyle(.secondary)
            Text("Brain Wi-Fi and IP settings are changed over encrypted Bluetooth only. When Bluetooth is out of range, saved message and mascot controls can use the authenticated S3 Brain LAN connection.")
                .font(.caption2).foregroundStyle(.secondary)
            Text("LAN fallback requires the phone and Brain to reach each other on the same subnet; IoT guest isolation can block access. Provisioning and first LAN-key exchange require Brain Bluetooth.")
                .font(.caption2).foregroundStyle(.secondary)
        }
        .padding()
        .background(.white.opacity(0.07))
        .clipShape(RoundedRectangle(cornerRadius: 16))
        .sheet(isPresented: $showingIPSettings) { ipSettingsPopup }
    }

    private var ipSettingsPopup: some View {
        NavigationStack {
            Form {
                Section("Address assignment") {
                    Toggle("Automatic (DHCP)", isOn: $wifiDHCPSelection)
                }
                if !wifiDHCPSelection {
                    Section("Static IPv4") {
                        TextField("IP address", text:$staticIP)
                            .keyboardType(.numbersAndPunctuation)
                        TextField("Subnet mask", text:$staticMask)
                            .keyboardType(.numbersAndPunctuation)
                        TextField("Default gateway", text:$staticGateway)
                            .keyboardType(.numbersAndPunctuation)
                        TextField("DNS server", text:$staticDNS)
                            .keyboardType(.numbersAndPunctuation)
                    }
                }
                Section {
                    Text("Settings are sent over Bluetooth. Reconnect Wi-Fi after applying to activate the new address.")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
            .navigationTitle("Wi-Fi IP Settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement:.cancellationAction) {
                    Button("Cancel") { showingIPSettings = false }
                }
                ToolbarItem(placement:.confirmationAction) {
                    Button("Apply") {
                        bluetooth.configureIP(dhcp:wifiDHCPSelection,
                             ip:staticIP,mask:staticMask,
                             gateway:staticGateway,dns:staticDNS)
                        showingIPSettings = false
                    }
                }
            }
        }
    }

    // MARK: Device Status

    private var deviceStatusSection: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Label("Device Status", systemImage: "cpu").font(.headline)
                Spacer()
                Text(bluetooth.isSimulator ? "DEMO" : bluetooth.isConnected ? "CONNECTED" : "OFFLINE")
                    .font(.caption2.bold())
                    .foregroundStyle(bluetooth.isConnected ? .green : .gray)
            }
            Divider()
            HStack(spacing: 14) {
                Image(systemName: batteryIcon)
                    .font(.system(size: 34))
                    .foregroundStyle(batteryColor)
                    .frame(width: 45)
                VStack(alignment: .leading, spacing: 8) {
                    Text("LILYGO BATTERY")
                        .font(.caption.bold())
                        .foregroundStyle(.gray)
                    HStack {
                        Text(batteryText)
                            .font(.system(size: 30, weight: .bold, design: .rounded))
                            .monospacedDigit()
                        Spacer()
                        Text(bluetooth.isSimulator ? "Demo" : bluetooth.isConnected ? "Live" : "Offline")
                            .font(.caption)
                            .foregroundStyle(.gray)
                    }
                    ProgressView(value: Double(bluetooth.batteryLevel ?? 0), total: 100)
                        .tint(batteryColor)
                }
            }
            VStack(alignment: .leading, spacing: 8) {
                Toggle("Low battery notifications", isOn: Binding(
                    get: { bluetooth.lowBatteryAlertsEnabled },
                    set: { enabled in
                        bluetooth.setLowBatteryAlerts(enabled)
                        if bluetooth.isConnected && !previewOnly {
                            bluetooth.sendControlCommand("L:\(enabled ? bluetooth.lowBatteryThreshold : 0)")
                        }
                    }
                )).tint(.orange)
                HStack {
                    Text("Alert when battery reaches")
                    Spacer()
                    Picker("Low battery threshold", selection: Binding(
                        get: { bluetooth.lowBatteryThreshold },
                        set: { value in
                            bluetooth.setLowBatteryThreshold(value)
                            if bluetooth.isConnected && !previewOnly && bluetooth.lowBatteryAlertsEnabled {
                                bluetooth.sendControlCommand("L:\(value)")
                            }
                        }
                    )) {
                        Text("10%").tag(10)
                        Text("15%").tag(15)
                        Text("20%").tag(20)
                        Text("25%").tag(25)
                        Text("30%").tag(30)
                    }.pickerStyle(.menu)
                }
                Text("Notifications use actual Bluetooth battery updates. iOS may delay updates while the app is suspended or force-closed.")
                    .font(.caption2).foregroundStyle(.secondary)
            }
            Divider()
            if bluetooth.isConnected {
                VStack(alignment: .leading, spacing: 9) {
                    Text("BATTERY & POWER").font(.caption.bold()).foregroundStyle(.secondary)
                    HStack {
                        powerMetric("Voltage", bluetooth.batteryVoltage.map { String(format: "%.3f V", $0) } ?? "—")
                        powerMetric("Current", bluetooth.batteryCurrent.map { String(format: "%+.0f mA", $0 * 1000) } ?? "—")
                    }
                    HStack {
                        powerMetric("Battery power", batteryPowerText)
                        powerMetric("State", batteryStateText)
                    }
                    HStack {
                        powerMetric("Battery health", bluetooth.batteryHealth.map { "\($0)%" } ?? "—")
                        powerMetric("Temperature", bluetooth.batteryTemperature.map { "\($0) °C" } ?? "—")
                    }
                    HStack {
                        powerMetric("Time to empty", displayedBatteryTime(bluetooth.minutesToEmpty, when: "Discharging"))
                        powerMetric("Time to full", displayedBatteryTime(bluetooth.minutesToFull, when: "Charging"))
                    }
                    if let updated = bluetooth.lastPowerUpdate {
                        Text("Last updated: \(updated.formatted(date: .omitted, time: .standard))")
                            .font(.caption2).foregroundStyle(.secondary)
                    }
                    Text("Power is battery-side voltage × current, not total USB input power.")
                        .font(.caption2).foregroundStyle(.secondary)
                }
                Divider()
            }
            HStack {
                Label(bluetooth.rememberedDeviceID == nil ? "No paired Brain" : "S3 Brain remembered", systemImage: "checkmark.shield")
                    .font(.subheadline)
                Spacer()
            }
            if !bluetooth.authorizedDevices.isEmpty {
                Picker("Authorized S3 Brain", selection: Binding(
                    get: { bluetooth.rememberedDeviceID ?? "" },
                    set: { bluetooth.selectAuthorizedDevice($0) }
                )) {
                    ForEach(bluetooth.authorizedDevices) { device in
                        Text(device.title).tag(device.id)
                    }
                }
                .pickerStyle(.menu)
                Text("All Bluetooth, Wi-Fi, gateway, DNS and IP settings belong to the S3 Brain. The LILYGO's radios remain off.")
                    .font(.caption2).foregroundStyle(.secondary)
            }
            Divider()
            VStack(alignment: .leading, spacing: 10) {
                Label("Audio", systemImage: "waveform").font(.headline)
                Text("Microphone gain")
                    .font(.subheadline.bold())
                HStack {
                    Slider(value: $micGain, in: 0...300, step: 10) { editing in
                        if !editing {
                            let level = Int(micGain)
                            UserDefaults.standard.set(micGain, forKey: "cuteMicGain")
                            bluetooth.sendControlCommand("A:MIC:\(level)")
                        }
                    }
                    Text("\(Int(micGain))%").monospacedDigit().frame(width: 52)
                }
                Text("Speaker volume")
                    .font(.subheadline.bold())
                HStack {
                    Slider(value: $speakerVolume, in: 0...100, step: 5) { editing in
                        if !editing {
                            let level = Int(speakerVolume)
                            UserDefaults.standard.set(speakerVolume, forKey: "cuteSpeakerVolume")
                            bluetooth.sendControlCommand("A:SPK:\(level)")
                        }
                    }
                    Text("\(Int(speakerVolume))%").monospacedDigit().frame(width: 52)
                }
                Button {
                    guard bluetooth.bluetoothBrainConnected, !audioTestRunning else { return }
                    audioTestRunning = true
                    audioTestPhase = "Please talk"
                    bluetooth.sendControlCommand("A:TEST")
                    Task { @MainActor in
                        try? await Task.sleep(for: .seconds(2))
                        audioTestPhase = "Playing"
                        try? await Task.sleep(for: .seconds(3))
                        audioTestPhase = "Ready"
                        audioTestRunning = false
                    }
                } label: {
                    Label(audioTestRunning ? audioTestPhase : "Test microphone & speaker", systemImage: "waveform")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .disabled(!bluetooth.bluetoothBrainConnected || audioTestRunning)
                if audioTestRunning {
                    Text(audioTestPhase == "Please talk" ? "Speak into Kitty's microphone for two seconds." : "Listen to your recording.")
                        .font(.caption).foregroundStyle(.secondary)
                }
                Button("Apply audio levels") {
                    UserDefaults.standard.set(micGain, forKey: "cuteMicGain")
                    UserDefaults.standard.set(speakerVolume, forKey: "cuteSpeakerVolume")
                    bluetooth.sendControlCommand("A:MIC:\(Int(micGain))")
                    bluetooth.sendControlCommand("A:SPK:\(Int(speakerVolume))")
                }
                .buttonStyle(.bordered)
                .disabled(!bluetooth.bluetoothBrainConnected)
                Text("Levels are saved on the S3 and affect local microphone playback tests. Microphone gain does not change the physical microphone hardware. Test at low speaker volume first.")
                    .font(.caption2).foregroundStyle(.secondary)
            }
            Toggle("Auto-reconnect Brain Bluetooth", isOn: Binding(
                get: { bluetooth.autoReconnect },
                set: { bluetooth.setAutoReconnect($0) }
            )).tint(.green)
            HStack {
                Button("Pair New Device") { bluetooth.pairNewDevice() }.buttonStyle(.bordered)
                Spacer()
                Button("Forget Device", role: .destructive) { bluetooth.forgetDevice() }
                    .buttonStyle(.bordered)
                    .disabled(bluetooth.rememberedDeviceID == nil)
            }
            Divider()
            HStack(spacing: 8) {
                Image(systemName: bluetooth.bluetoothBrainConnected ? "bluetooth" :
                      bluetooth.wifiFallbackConnected ? "wifi" : "antenna.radiowaves.left.and.right")
                    .foregroundStyle(bluetooth.isConnected ? .green : .orange)
                Text(bluetooth.isSimulator ? "Simulator / Demo Mode" :
                     bluetooth.bluetoothBrainConnected ? "S3 Brain • Bluetooth (preferred)" :
                     bluetooth.wifiFallbackConnected ? "S3 Brain • Local Wi-Fi fallback" : bluetooth.status)
                    .font(.subheadline)
                    .lineLimit(3)
                Spacer()
            }
            if bluetooth.isConnected && !bluetooth.isSimulator {
                Button {
                    restoreAfterConnection()
                } label: {
                    Label("Reapply Saved Display Settings", systemImage: "arrow.clockwise")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered)

                Text("The app prefers Brain Bluetooth, automatically retries a remembered Brain when reachable, and falls back to Brain Wi-Fi if needed. iOS may delay background reconnection.")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
            if !bluetooth.isSimulator {
                Button {
                    if bluetooth.isConnected { bluetooth.disconnect() }
                    else { bluetooth.connect() }
                } label: {
                    Label(bluetooth.isConnected ? "Disconnect" : bluetooth.isScanning ? "Searching..." : "Connect to Brain",
                          systemImage: "bluetooth")
                        .frame(maxWidth: .infinity)
                        .padding(12)
                        .background(bluetooth.isConnected ? Color.gray.opacity(0.5) : .blue)
                        .clipShape(RoundedRectangle(cornerRadius: 12))
                }
                .buttonStyle(.plain)
                .disabled(bluetooth.isScanning)
            }
        }
        .padding()
        .background(.white.opacity(0.07))
        .clipShape(RoundedRectangle(cornerRadius: 18))
    }

    private var batteryPowerText: String {
        guard let voltage = bluetooth.batteryVoltage, let current = bluetooth.batteryCurrent else { return "—" }
        return String(format: "%.2f W", abs(voltage * current))
    }
    private var batteryStateText: String {
        guard let amps = bluetooth.batteryCurrent else { return "—" }
        return amps > 0.005 ? "Charging" : amps < -0.005 ? "Discharging" : "Idle"
    }
    private func powerMetric(_ title: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title).font(.caption2).foregroundStyle(.secondary)
            Text(value).font(.subheadline.bold()).monospacedDigit()
                .minimumScaleFactor(0.75).lineLimit(1)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(10)
        .background(.white.opacity(0.06))
        .clipShape(RoundedRectangle(cornerRadius: 10))
    }
    private var batteryText: String {
        guard !bluetooth.isSimulator, bluetooth.isConnected, let level = bluetooth.batteryLevel else { return "—" }
        return "\(level)%"
    }
    private var batteryColor: Color {
        guard bluetooth.isConnected, let level = bluetooth.batteryLevel else { return .gray }
        return level <= 15 ? .red : level <= 30 ? .orange : .green
    }
    private var batteryIcon: String {
        guard bluetooth.isConnected, let level = bluetooth.batteryLevel else { return "battery.0percent" }
        if level <= 10 { return "battery.0percent" }
        if level <= 35 { return "battery.25percent" }
        if level <= 60 { return "battery.50percent" }
        if level <= 85 { return "battery.75percent" }
        return "battery.100percent"
    }

    // MARK: LCD Preview

    private var displayPreview: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                sectionTitle("LCD PREVIEW")
                Spacer()
            }
            ZStack {
                RoundedRectangle(cornerRadius: 14)
                    .fill(lcdBackground)
                HStack(spacing: 4) {
                        Text(message.isEmpty ? "こんにちわ" : message)
                            .font(.system(size: CGFloat(10 + messageFontSize * 5), weight: .bold))
                            .foregroundStyle(speechBubbleEnabled ? Color.black : themeColor)
                            .lineLimit(2)
                            .minimumScaleFactor(0.5)
                            .multilineTextAlignment(.center)
                            .frame(maxWidth: .infinity)
                            .padding(speechBubbleEnabled ? 10 : 0)
                            .background {
                                if speechBubbleEnabled {
                                    RoundedRectangle(cornerRadius: 14)
                                        .fill(themeColor)
                                        .overlay {
                                            RoundedRectangle(cornerRadius: 14)
                                                .fill(Color.white.opacity(0.78))
                                        }
                                        .overlay {
                                            RoundedRectangle(cornerRadius: 14)
                                                .strokeBorder(themeColor, lineWidth: 2)
                                        }
                                }
                            }
                        if showMascot {
                            VStack(spacing: 0) {
                                if accessoryStyle > 0 && accessoryStyle < 8 {
                                    Text(["", "👓", "🎀", "👑", "🧣", "🎉", "🌸", "✨"][accessoryStyle])
                                        .font(.system(size: 12))
                                }
                                Text(selectedMood == .sleepy ? "😴" : selectedCharacter.symbol)
                                if heldObjectMode == 1 && heldObject > 0 && heldObject < 8 {
                                    Text(["", "❤️", "💐", "🧁", "🛏️", "🪄", "🧻", "☁️"][heldObject])
                                        .font(.system(size: 12))
                                }
                            }
                                .font(.system(size: 48 * CGFloat(mascotSize) / 100))
                                .frame(width: mascotPreviewWidth)
                                .frame(maxHeight: .infinity)
                                .background(lcdMascotBackground)
                        }
                    }
                    .padding(9)
            }
            .aspectRatio(320.0 / 170.0, contentMode: .fit)
            .clipped()
            Text("Illustrative preview; Japanese characters are sent as small font glyphs.")
                .font(.caption2)
                .foregroundStyle(.gray)
        }
    }

    private var themeSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            sectionTitle("OVERALL COLOR THEME")
            LazyVGrid(columns: Array(repeating: GridItem(.flexible()), count: 5), spacing: 8) {
                ForEach(0..<themeNames.count, id: \.self) { index in
                    Button {
                        selectedTheme = index
                        UserDefaults.standard.set(index, forKey: "displayTheme")
                        if shouldAutoSend { bluetooth.setTheme(index) }
                    } label: {
                        VStack(spacing: 5) {
                            Circle()
                                .fill(themeColors[index])
                                .frame(width: 28, height: 28)
                                .overlay {
                                    Circle().stroke(.white,
                                        lineWidth: selectedTheme == index ? 3 : 0)
                                }
                            Text(themeNames[index])
                                .font(.system(size: 9))
                        }
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 9)
                        .background(.white.opacity(selectedTheme == index ? 0.16 : 0.05))
                        .clipShape(RoundedRectangle(cornerRadius: 10))
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }

    // MARK: - Open WebUI (AI-SERVER) text integration
    // The iPhone provisions the S3 securely over BLE; S3 owns HTTPS AI streaming.
    private var aiSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            sectionTitle("KITTY AI — OPEN WEBUI")
            TextField("https://AI-SERVER.example", text: $aiServer)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .textFieldStyle(.roundedBorder)
            TextField("Open WebUI model ID", text: $aiModel)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .textFieldStyle(.roundedBorder)
            SecureField("Open WebUI user API key (sk-)", text: $aiAPIKey)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .textFieldStyle(.roundedBorder)
            Text("Normal Kitty AI and realtime voice calls use the same Open WebUI user API key. The iPhone stores it in Keychain and sends it to S3 over encrypted Bluetooth; browser 2FA stays unchanged.")
                .font(.caption2)
                .foregroundStyle(.secondary)
            Button("Save Open WebUI connection") {
                let server = aiServer.trimmingCharacters(in: .whitespacesAndNewlines)
                let model = aiModel.trimmingCharacters(in: .whitespacesAndNewlines)
                let key = aiAPIKey.trimmingCharacters(in: .whitespacesAndNewlines)
                guard server.hasPrefix("https://"), !server.contains("@"),
                      !model.isEmpty, key.hasPrefix("sk-"),
                      key.utf8.count > 20, key.utf8.count <= 8192 else {
                    aiStatus = "Enter HTTPS URL, model ID and complete Open WebUI sk- user API key"
                    return
                }
                UserDefaults.standard.set(server, forKey: "cuteAIServer")
                UserDefaults.standard.set(model, forKey: "cuteAIModel")
                CuteAISecret.save(key)
                if bluetooth.bluetoothBrainConnected {
                    bluetooth.saveBrainAIConnection(url: server, model: model, key: key)
                    aiStatus = "Provisioning URL, model and shared realtime API key over encrypted BLE; check command status for errors"
                } else {
                    aiStatus = "Saved on iPhone. Connect S3 over Bluetooth and tap Save again to transfer."
                }
            }
            .buttonStyle(.bordered)
            Button {
                let key = aiAPIKey.trimmingCharacters(in: .whitespacesAndNewlines)
                guard key.hasPrefix("sk-"), key.utf8.count > 20,
                      key.utf8.count <= 8192 else {
                    aiStatus = "Enter a complete Open WebUI sk- user API key before syncing"
                    return
                }
                CuteAISecret.save(key)
                bluetooth.saveBrainAIKey(key)
                aiStatus = "Syncing the shared AI/realtime key to S3 over encrypted BLE. Existing URL and model are unchanged."
            } label: {
                Label("Update API Key on S3", systemImage: "key.fill")
            }
            .buttonStyle(.bordered)
            .disabled(!bluetooth.bluetoothBrainConnected)
            Text("Changed the key? Connect S3 Bluetooth and tap Update API Key on S3. End any active call first; the new key applies to the next call.")
                .font(.caption2)
                .foregroundStyle(.secondary)
            HStack(spacing: 10) {
                Label("Conversation", systemImage: "bubble.left.and.bubble.right")
                    .font(.subheadline.bold())
                Spacer()
                Button {
                    bluetooth.sendControlCommand("AI:NEW")
                    aiQuestion = ""
                    lastSubmittedAIQuestion = ""
                    aiResponse = ""
                    aiStatus = "New conversation requested; previous context will be cleared on S3."
                } label: {
                    Label("New conversation", systemImage: "plus.circle")
                }
                .buttonStyle(.bordered)
                .disabled(!bluetooth.bluetoothBrainConnected)
            }
            Text("Kitty remembers up to 4 recent exchanges for 24 hours from the first completed reply, even after an S3 reboot. New conversation clears them immediately. The display returns to your normal message 2 minutes after an AI reply.")
                .font(.caption)
                .foregroundStyle(.secondary)
            TextField("Ask Kitty something...", text: $aiQuestion, axis: .vertical)
                .lineLimit(2...4)
                .textFieldStyle(.roundedBorder)
            Toggle("Show AI answer on Kitty", isOn: $aiSendToKitty)
                .tint(.pink)
            Button("Test S3 AI Bluetooth link") {
                bluetooth.sendControlCommand("AI:PING")
                aiStatus = "AI ping sent via Bluetooth; check connection status below and S3 Serial Monitor"
            }
            .buttonStyle(.bordered)
            .disabled(!bluetooth.bluetoothBrainConnected)
            Text("S3 command status: " + bluetooth.status)
                .font(.caption2)
                .foregroundStyle(.secondary)
            Button {
                Task { await askKittyAI() }
            } label: {
                Label(aiBusy ? "Asking AI..." : "Ask Kitty AI", systemImage: "bubble.left.and.text.bubble.right")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .disabled(aiBusy || aiQuestion.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            HStack(spacing: 12) {
                Button {
                    bluetooth.sendControlCommand("AI:STOP")
                    aiStatus = "Stop requested. Waiting for S3 confirmation."
                } label: {
                    Label("Stop AI", systemImage: "stop.fill")
                }
                .buttonStyle(.bordered)
                .disabled(!bluetooth.bluetoothBrainConnected ||
                    !["Sending prompt", "Queued", "Connecting to AI server", "Kitty is responding"].contains(bluetooth.aiLiveStatus))
                Button {
                    aiQuestion = lastSubmittedAIQuestion
                    Task { await askKittyAI() }
                } label: {
                    Label("Retry", systemImage: "arrow.clockwise")
                }
                .buttonStyle(.bordered)
                .disabled(!bluetooth.bluetoothBrainConnected || lastSubmittedAIQuestion.isEmpty ||
                    ["Sending prompt", "Queued", "Connecting to AI server", "Kitty is responding", "Stopping"].contains(bluetooth.aiLiveStatus))
            }
            if !aiResponse.isEmpty {
                Text(aiResponse).font(.subheadline).textSelection(.enabled)
            }
            Button {
                if bluetooth.aiLiveStatus == "Voice recording" {
                    bluetooth.sendControlCommand("A:VOICE:STOP")
                    bluetooth.aiLiveStatus = "Uploading voice"
                    aiStatus = "Recording finished. Sending audio to Open WebUI."
                } else {
                    bluetooth.aiLiveStatus = "Voice recording"
                    bluetooth.sendControlCommand("A:VOICE")
                    aiStatus = "Speak now, then tap Stop & Send. Automatically stops after 30 seconds."
                }
            } label: {
                Label(bluetooth.aiLiveStatus == "Voice recording" ? "Stop & Send" : "Talk to Kitty (30 sec max)",
                      systemImage: bluetooth.aiLiveStatus == "Voice recording" ? "stop.circle.fill" : "mic.fill")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .disabled(!bluetooth.bluetoothBrainConnected ||
                (bluetooth.aiLiveStatus != "Voice recording" &&
                 ["Queued", "Connecting to AI server", "Kitty is responding", "Stopping", "Uploading voice"].contains(bluetooth.aiLiveStatus)))
            Text("Uses S3 microphone and your existing Open WebUI speech-to-text service. The transcript becomes the next Kitty AI prompt.")
                .font(.caption2).foregroundStyle(.secondary)
            Button("Test S3 AI command connection") {
                bluetooth.sendControlCommand("AI:PING")
                aiStatus = "AI:PING queued; check Bluetooth status and S3 Serial Monitor"
            }
            .buttonStyle(.bordered)
            .disabled(!bluetooth.bluetoothBrainConnected)
            HStack(spacing: 8) {
                Image(systemName: bluetooth.aiLiveStatus.hasPrefix("Failed:") ? "exclamationmark.triangle" :
                      bluetooth.aiLiveStatus == "Complete" ? "checkmark.circle" : "waveform")
                Text("AI status: " + bluetooth.aiLiveStatus)
                    .font(.subheadline)
            }
            .foregroundStyle(bluetooth.aiLiveStatus.hasPrefix("Failed:") ? Color.orange : Color.primary)
            Text("Bluetooth transport: " + bluetooth.status)
                .font(.caption2).foregroundStyle(.secondary)
            Text(aiStatus).font(.caption2).foregroundStyle(.secondary)
            Text("Realtime voice (experimental): S3 uses the same HTTPS Open WebUI server and saved sk- key. Server authentication passed; physical mic and speaker operation still needs testing.")
                .font(.caption2).foregroundStyle(.secondary)
        }
        .padding()
        .background(.white.opacity(0.07))
        .clipShape(RoundedRectangle(cornerRadius: 16))
    }

    private func kittyPages(_ text: String) -> [String] {
        // Limit AI text to short, readable pages for the fixed-size LCD
        // speech bubble (the underlying BLE/C5 protocol still allows 96 bytes).
        // Iterate by Swift Character so Japanese and emoji remain intact.
        var pages: [String] = []
        var page = ""
        let normalized = text.trimmingCharacters(in: .whitespacesAndNewlines)
        for character in normalized {
            let part = String(character)
            if (page + part).utf8.count > 90 {
                if !page.isEmpty { pages.append(page) }
                page = part.utf8.count <= 90 ? part : ""
            } else {
                page += part
            }
        }
        if !page.isEmpty { pages.append(page) }
        return pages
    }

    @MainActor private func showKittyAIPages(_ answer: String) {
        aiDisplayTask?.cancel()
        let pages = kittyPages(answer)
        guard !pages.isEmpty else { return }
        aiDisplayTask = Task { @MainActor in
            bluetooth.sendControlCommand("AI:ON")
            for (index, page) in pages.enumerated() {
                guard !Task.isCancelled else { return }
                guard bluetooth.isConnected else {
                    aiStatus = "Kitty disconnected; AI answer remains on iPhone"
                    return
                }
                bluetooth.sendMessage(page)
                aiStatus = "Showing AI answer on Kitty: page \(index + 1)/\(pages.count)"
                if index + 1 < pages.count {
                    // Allow BLE glyph transfers and enough reading time.
                    try? await Task.sleep(for: .seconds(14))
                }
            }
            if !Task.isCancelled {
                aiStatus = "AI answer displayed on Kitty (\(pages.count) pages)"
            }
        }
    }

    @MainActor private func askKittyAI() async {
        let prompt = aiQuestion.trimmingCharacters(in: .whitespacesAndNewlines)
        let server = aiServer.trimmingCharacters(in: .whitespacesAndNewlines)
        let model = aiModel.trimmingCharacters(in: .whitespacesAndNewlines)
        let secret = aiAPIKey.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !prompt.isEmpty else { return }
        guard bluetooth.bluetoothBrainConnected else {
            aiStatus = "Connect to S3 Brain over encrypted Bluetooth first"
            return
        }
        guard server.hasPrefix("https://"), !model.isEmpty,
              !secret.isEmpty else {
            aiStatus = "Enter HTTPS URL, model and API key"
            return
        }
        lastSubmittedAIQuestion = prompt
        aiResponse = ""
        aiStatus = "Prompt queued on S3 Brain. The S3 will contact Open WebUI over Wi-Fi."
        bluetooth.sendBrainAIPrompt(url: server, model: model, key: secret,
                                    prompt: prompt)
    }

    // MARK: Message mode

    private var messageSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            sectionTitle("MESSAGE")
            Toggle("Speech bubble mode", isOn: $speechBubbleEnabled)
                .tint(.pink)
                .onChange(of: speechBubbleEnabled) { _, enabled in
                    UserDefaults.standard.set(enabled, forKey: "speechBubbleEnabled")
                    if shouldAutoSend { bluetooth.sendControlCommand("Q:\(enabled ? 1 : 0)") }
                }
            if speechBubbleEnabled {
                Toggle("Typewriter animation", isOn: $speechTypewriter)
                    .tint(.pink)
                    .onChange(of: speechTypewriter) { _, enabled in
                        UserDefaults.standard.set(enabled, forKey: "speechTypewriter")
                        if shouldAutoSend { bluetooth.sendControlCommand("Y:\(enabled ? 1 : 0)") }
                    }
                Text("Shows the message in a bubble beside the animated mascot. The bubble can be turned off at any time.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            TextField("Your message", text: $message, axis: .vertical)
                .lineLimit(2...4)
                .padding()
                .background(.white.opacity(0.09))
                .clipShape(RoundedRectangle(cornerRadius: 12))
                .textInputAutocapitalization(.characters)
                .autocorrectionDisabled()
            Text("\(message.utf8.count) / 96 bytes")
                .font(.caption)
                .foregroundStyle(message.utf8.count > 96 ? .red : .gray)
            actionButton("Send Message", color: .pink) {
                bluetooth.sendMessage(message)
                appNotice = bluetooth.isSimulator ? "Demo only — nothing sent over Bluetooth." : ""
            }
            .disabled(!canSend || message.isEmpty || message.utf8.count > 96)
            sectionTitle("QUICK MESSAGES")
            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 8) {
                ForEach(quickMessages, id: \.self) { text in
                    Button {
                        message = text
                        if shouldAutoSend { bluetooth.sendMessage(text) }
                    } label: {
                        Text(text)
                            .font(.caption.bold())
                            .frame(maxWidth: .infinity)
                            .frame(height: 48)
                            .background(.white.opacity(0.08))
                            .clipShape(RoundedRectangle(cornerRadius: 10))
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }

    // MARK: Character selection

    private var characterSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            sectionTitle("CHOOSE A CHARACTER")
            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible()), GridItem(.flexible())], spacing: 8) {
                ForEach(CuteCharacter.allCases) { character in
                    Button {
                        selectedCharacter = character
                        UserDefaults.standard.set(character.rawValue, forKey: "selectedCharacter")
                        if shouldAutoSend { bluetooth.sendMessage("C:\(character.rawValue)") }
                    } label: {
                        VStack(spacing: 8) {
                            Text(character.symbol).font(.system(size: 35))
                            Text(character.title)
                                .font(.caption2)
                                .lineLimit(1)
                                .minimumScaleFactor(0.6)
                        }
                        .frame(maxWidth: .infinity)
                        .frame(height: 86)
                        .background(selectedCharacter == character ? themeColor.opacity(0.24) : Color.white.opacity(0.07))
                        .overlay {
                            RoundedRectangle(cornerRadius: 12)
                                .stroke(selectedCharacter == character ? themeColor : Color.clear, lineWidth: 2)
                        }
                        .clipShape(RoundedRectangle(cornerRadius: 12))
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }

    // MARK: - Animated mascot mood
    private var moodSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            sectionTitle("MASCOT EXPRESSION")
            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible()), GridItem(.flexible()), GridItem(.flexible())], spacing: 8) {
                ForEach(CuteMood.allCases) { mood in
                    Button {
                        selectedMood = mood
                        UserDefaults.standard.set(mood.rawValue, forKey: "mascotMood")
                        if shouldAutoSend { bluetooth.sendMessage("M:\(mood.rawValue)") }
                    } label: {
                        VStack(spacing: 4) {
                            Text(mood.symbol).font(.title2)
                            Text(mood.title).font(.caption2).minimumScaleFactor(0.7).lineLimit(1)
                        }
                        .frame(maxWidth: .infinity).frame(height: 62)
                        .background(selectedMood == mood ? themeColor.opacity(0.24) : Color.white.opacity(0.07))
                        .clipShape(RoundedRectangle(cornerRadius: 10))
                        .overlay(RoundedRectangle(cornerRadius: 10).stroke(selectedMood == mood ? themeColor : .clear, lineWidth: 2))
                    }.buttonStyle(.plain)
                }
            }
            Toggle("Surprise animations", isOn: $surpriseAnimationsEnabled)
                .tint(themeColor)
                .onChange(of: surpriseAnimationsEnabled) { _, enabled in
                    UserDefaults.standard.set(enabled, forKey: "surpriseAnimationsEnabled")
                    if shouldAutoSend { bluetooth.sendControlCommand("S:\(enabled ? 1 : 0)") }
                }
            Text("Occasionally, the mascot sneezes, stretches, looks around, gets startled or notices a butterfly. Turn this off to keep only the regular mood animations.")
                .font(.caption).foregroundStyle(.secondary)
            Text("Expressions animate on the device, even without an active Bluetooth connection.")
                .font(.caption).foregroundStyle(.secondary)
        }
    }

    // MARK: - Mascot customization
    private func sendMascotCustomization() {
        guard canSend else { return }
        bluetooth.configureMascot(accessory: accessoryStyle,
                                   objectMode: heldObjectMode,
                                   object: heldObject,
                                   frequency: animationFrequency,
                                   intensity: animationIntensity,
                                   personality: personalityAnimations)
    }

    private var mascotCustomizationSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            sectionTitle("MASCOT CUSTOMIZATION")

            Picker("Accessory", selection: $accessoryStyle) {
                ForEach(0..<accessoryNames.count, id: \.self) { index in
                    Text(accessoryNames[index]).tag(index)
                }
            }
            .onChange(of: accessoryStyle) { _, value in
                UserDefaults.standard.set(value, forKey: "cuteAccessoryStyle")
                if shouldAutoSend { bluetooth.sendControlCommand("A:\(value)") }
            }

            Picker("Held object", selection: $heldObjectMode) {
                Text("Automatic from mood").tag(0)
                Text("Choose manually").tag(1)
            }
            .pickerStyle(.segmented)
            .onChange(of: heldObjectMode) { _, value in
                UserDefaults.standard.set(value, forKey: "cuteHeldObjectMode")
                if shouldAutoSend { bluetooth.sendControlCommand("H:\(value)") }
            }

            if heldObjectMode == 1 {
                Picker("Object", selection: $heldObject) {
                    ForEach(0..<objectNames.count, id: \.self) { index in
                        Text(objectNames[index]).tag(index)
                    }
                }
                .onChange(of: heldObject) { _, value in
                    UserDefaults.standard.set(value, forKey: "cuteHeldObject")
                    if shouldAutoSend { bluetooth.sendControlCommand("J:\(value)") }
                }
            }

            Picker("Animation frequency", selection: $animationFrequency) {
                Text("Relaxed").tag(0)
                Text("Normal").tag(1)
                Text("Lively").tag(2)
            }
            .pickerStyle(.segmented)
            .onChange(of: animationFrequency) { _, value in
                UserDefaults.standard.set(value, forKey: "cuteAnimationFrequency")
                if shouldAutoSend { bluetooth.sendControlCommand("K:\(value)") }
            }

            Picker("Animation intensity", selection: $animationIntensity) {
                Text("Subtle").tag(0)
                Text("Normal").tag(1)
                Text("Expressive").tag(2)
            }
            .pickerStyle(.segmented)
            .onChange(of: animationIntensity) { _, value in
                UserDefaults.standard.set(value, forKey: "cuteAnimationIntensity")
                if shouldAutoSend { bluetooth.sendControlCommand("I:\(value)") }
            }

            Toggle("Individual mascot personality", isOn: $personalityAnimations)
                .tint(themeColor)
                .onChange(of: personalityAnimations) { _, value in
                    UserDefaults.standard.set(value, forKey: "cutePersonalityAnimations")
                    if shouldAutoSend { bluetooth.sendControlCommand("N:\(value ? 1 : 0)") }
                }

            HStack(spacing: 8) {
                Button("Random") { bluetooth.previewMascotAnimation(0) }
                Button("Mood") { bluetooth.previewMascotAnimation(1) }
                Button("Personality") { bluetooth.previewMascotAnimation(2) }
            }
            .buttonStyle(.bordered)
            .disabled(!canSend)

            Text("Use the buttons to preview animations immediately. The mascot remains on the right and does not change size.")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    // MARK: - Saved display profiles
    private func saveProfile() {
        let proposed=newProfileName.trimmingCharacters(in: .whitespacesAndNewlines)
        let label=proposed.isEmpty ? "Profile \(displayProfiles.count + 1)" : proposed
        let profile=CuteDisplayProfile(
            name: label, message: message,
            theme: selectedTheme, character: selectedCharacter.rawValue,
            mood: selectedMood.rawValue, visible: showMascot,
            mascotSize: mascotSize, accessory: accessoryStyle,
            objectMode: heldObjectMode, heldObject: heldObject,
            frequency: animationFrequency, intensity: animationIntensity,
            personality: personalityAnimations, fontSize: messageFontSize,
            bubble: speechBubbleEnabled, typewriter: speechTypewriter,
            brightness: brightness)
        displayProfiles.append(profile)
        persistProfiles()
        newProfileName=""
    }

    private func persistProfiles() {
        if let data=try? JSONEncoder().encode(displayProfiles) {
            UserDefaults.standard.set(data,forKey:"cuteSavedProfiles")
        }
    }

    private func loadProfile(_ profile: CuteDisplayProfile) {
        // A loaded profile applies immediately when connected.
        message=profile.message
        selectedTheme=max(0,min(24,profile.theme))
        selectedCharacter=CuteCharacter(rawValue:profile.character) ?? .kitty
        selectedMood=CuteMood(rawValue:profile.mood) ?? .happy
        showMascot=profile.visible
        mascotSize=profile.mascotSize
        accessoryStyle=profile.accessory
        heldObjectMode=profile.objectMode
        heldObject=profile.heldObject
        animationFrequency=profile.frequency
        animationIntensity=profile.intensity
        personalityAnimations=profile.personality
        messageFontSize=profile.fontSize
        speechBubbleEnabled=profile.bubble
        speechTypewriter=profile.typewriter
        brightness=profile.brightness
        UserDefaults.standard.set(selectedTheme,forKey:"displayTheme")
        UserDefaults.standard.set(selectedCharacter.rawValue,forKey:"selectedCharacter")
        UserDefaults.standard.set(selectedMood.rawValue,forKey:"mascotMood")
        UserDefaults.standard.set(showMascot,forKey:"showMascot")
        UserDefaults.standard.set(mascotSize,forKey:"mascotSize")
        UserDefaults.standard.set(accessoryStyle,forKey:"cuteAccessoryStyle")
        UserDefaults.standard.set(heldObjectMode,forKey:"cuteHeldObjectMode")
        UserDefaults.standard.set(heldObject,forKey:"cuteHeldObject")
        UserDefaults.standard.set(animationFrequency,forKey:"cuteAnimationFrequency")
        UserDefaults.standard.set(animationIntensity,forKey:"cuteAnimationIntensity")
        UserDefaults.standard.set(personalityAnimations,forKey:"cutePersonalityAnimations")
        UserDefaults.standard.set(messageFontSize,forKey:"messageFontSize")
        UserDefaults.standard.set(speechBubbleEnabled,forKey:"speechBubbleEnabled")
        UserDefaults.standard.set(speechTypewriter,forKey:"speechTypewriter")
        if !previewOnly && bluetooth.isConnected { restoreAfterConnection() }
    }

    private var displayProfilesSection: some View {
        VStack(alignment:.leading,spacing:10) {
            sectionTitle("SAVED DISPLAY PROFILES")
            HStack {
                TextField("Profile name",text:$newProfileName)
                    .textFieldStyle(.roundedBorder)
                Button("Save") { saveProfile() }
                    .buttonStyle(.borderedProminent)
                    .disabled(displayProfiles.count>=12)
            }
            ForEach(displayProfiles) { profile in
                HStack {
                    VStack(alignment:.leading,spacing:2) {
                        Text(profile.name).font(.subheadline.bold())
                        Text(profile.message)
                            .font(.caption2).foregroundStyle(.secondary)
                            .lineLimit(1)
                    }
                    Spacer()
                    Button("Load") { loadProfile(profile) }
                        .buttonStyle(.bordered)
                    Button(role:.destructive) {
                        displayProfiles.removeAll{$0.id==profile.id}
                        persistProfiles()
                    } label:{ Image(systemName:"trash") }
                        .buttonStyle(.borderless)
                }
            }
            Text("Save up to 12 profiles on your iPhone. Loading a profile applies it immediately when connected.")
                .font(.caption2).foregroundStyle(.secondary)
        }
        .padding()
        .background(.white.opacity(0.07))
        .clipShape(RoundedRectangle(cornerRadius:16))
    }

    // MARK: - Character visibility, size and Message Mode font
    private var appearanceSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            sectionTitle("DISPLAY APPEARANCE")
            Toggle("Show character", isOn: $showMascot)
                .tint(themeColor)
                .onChange(of: showMascot) { _, value in
                    UserDefaults.standard.set(value, forKey: "showMascot")
                    if shouldAutoSend { bluetooth.sendMessage("V:\(value ? 1 : 0)") }
                }
            if showMascot {
                HStack {
                    Text("Character size")
                    Spacer()
                    Text("\(mascotSize)%").foregroundStyle(.secondary)
                }
                Picker("Character size", selection: $mascotSize) {
                    Text("Tiny").tag(40)
                    Text("Small").tag(60)
                    Text("Medium").tag(80)
                    Text("Large").tag(100)
                }
                .pickerStyle(.segmented)
                .onChange(of: mascotSize) { _, value in
                    UserDefaults.standard.set(value, forKey: "mascotSize")
                    if shouldAutoSend { bluetooth.sendMessage("Z:\(value)") }
                }
            }
            HStack {
                    Text("Message font size")
                    Spacer()
                    Text("\(messageFontSize) / 5").foregroundStyle(.secondary)
                }
                Slider(value: Binding(
                    get: { Double(messageFontSize) },
                    set: { messageFontSize = Int($0) }
                ), in: 1...5, step: 1) { editing in
                    if !editing {
                        UserDefaults.standard.set(messageFontSize, forKey: "messageFontSize")
                        if shouldAutoSend { bluetooth.sendMessage("F:\(messageFontSize)") }
                    }
                }
                .tint(themeColor)

            Text("Smaller mascots reserve less width, allowing more text. The board defaults to Happy Hello Kitty after restart; reapply your preferences from the app.")
                .font(.caption2)
                .foregroundStyle(.gray)
        }
        .padding()
        .background(.white.opacity(0.07))
        .clipShape(RoundedRectangle(cornerRadius: 16))
    }

    private var powerSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            sectionTitle("DEVICE POWER")
            Button {
                showingPowerConfirmation = true
            } label: {
                Label("Turn Display Off", systemImage: "power")
                    .fontWeight(.semibold)
                    .frame(maxWidth: .infinity)
                    .padding()
                    .background(Color.red.opacity(0.75))
                    .clipShape(RoundedRectangle(cornerRadius: 12))
            }
            .buttonStyle(.plain)
            .disabled(!bluetooth.isConnected || bluetooth.isSimulator)
            Text("Low-power deep sleep, not physical battery disconnection. Press the LILYGO RESET button to wake.")
                .font(.caption)
                .foregroundStyle(.gray)
        }
    }

    private var brightnessSection: some View {
        VStack(spacing: 12) {
            HStack {
                Label("Screen Brightness", systemImage: "sun.max.fill").foregroundStyle(.yellow)
                Spacer()
                Text("\(Int(brightness))%")
            }
            Toggle("Scheduled day/night brightness", isOn: $autoBrightness)
                .tint(themeColor)
                .onChange(of: autoBrightness) { _, v in
                    UserDefaults.standard.set(v, forKey: "cuteAutoBrightness")
                    if v { updateScheduledBrightness() }
                }
            if autoBrightness {
                Picker("Day begins", selection: $dayStart) {
                    ForEach(0..<24, id: \.self) { h in
                        Text(String(format: "%02d:00", h)).tag(h)
                    }
                }
                .onChange(of: dayStart) { _, v in
                    UserDefaults.standard.set(v, forKey: "cuteDayStart")
                    updateScheduledBrightness()
                }
                Picker("Night begins", selection: $nightStart) {
                    ForEach(0..<24, id: \.self) { h in
                        Text(String(format: "%02d:00", h)).tag(h)
                    }
                }
                .onChange(of: nightStart) { _, v in
                    UserDefaults.standard.set(v, forKey: "cuteNightStart")
                    updateScheduledBrightness()
                }
                HStack {
                    Text("Day")
                    Slider(value: $dayBrightness, in: 5...100, step: 5)
                    Text("\(Int(dayBrightness))%")
                }
                .onChange(of: dayBrightness) { _, v in
                    UserDefaults.standard.set(v, forKey: "cuteDayBrightness")
                    updateScheduledBrightness()
                }
                HStack {
                    Text("Night")
                    Slider(value: $nightBrightness, in: 5...100, step: 5)
                    Text("\(Int(nightBrightness))%")
                }
                .onChange(of: nightBrightness) { _, v in
                    UserDefaults.standard.set(v, forKey: "cuteNightBrightness")
                    updateScheduledBrightness()
                }
                Text("Time is checked while the app runs. iOS may suspend updates in the background.")
                    .font(.caption2).foregroundStyle(.secondary)
            }
            Slider(value: $brightness, in: 5...100, step: 5) { editing in
                if !editing && shouldAutoSend && !autoBrightness { bluetooth.setBrightness(Int(brightness)) }
            }
            .tint(.yellow)
        }
        .padding()
        .background(.white.opacity(0.07))
        .clipShape(RoundedRectangle(cornerRadius: 16))
    }

    private func sectionTitle(_ value: String) -> some View {
        Text(value).font(.caption.bold()).foregroundStyle(.gray)
    }

    private func actionButton(_ title: String, color: Color, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title).fontWeight(.semibold)
                .frame(maxWidth: .infinity)
                .padding()
                .background(color)
                .clipShape(RoundedRectangle(cornerRadius: 12))
        }
        .buttonStyle(.plain)
    }

    // Reapply the saved preferences only when explicitly requested, for example
    // after a firmware restart that reset the board defaults.
    private func restoreAfterConnection() {
        bluetooth.restoreState(
            theme: selectedTheme,
            character: selectedCharacter.rawValue,
            mood: selectedMood.rawValue,
            visible: showMascot,
            size: mascotSize,
            font: messageFontSize,
            bubble: speechBubbleEnabled,
            typewriter: speechTypewriter,
            brightness: Int(brightness),
            message: message
        )
        bluetooth.sendControlCommand("L:\(bluetooth.lowBatteryAlertsEnabled ? bluetooth.lowBatteryThreshold : 0)")
        bluetooth.sendControlCommand("S:\(surpriseAnimationsEnabled ? 1 : 0)")
        sendMascotCustomization()
        appNotice = "Connected — restoring CuteDisplay settings."
    }


}

#Preview {
    ContentView()
}