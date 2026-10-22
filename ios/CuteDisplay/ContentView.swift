import SwiftUI
import Foundation

struct DrinkItem: Identifiable, Codable, Equatable {
    var id = UUID()
    var name: String
    var count: Int
}

enum DisplayMode: String, CaseIterable {
    case message = "Message"
    case drinks = "Drinks"
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
    var mode: String
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
    var drinks: [DrinkItem]
}

struct ContentView: View {
    @StateObject private var bluetooth = BluetoothManager()
    @State private var mode: DisplayMode = .message
    @State private var message = UserDefaults.standard.string(forKey: "savedMessage") ?? "こんにちわ"
    @State private var brightness = 75.0
    @State private var wifiName = UserDefaults.standard.string(forKey: "cuteWiFiName") ?? ""
    @State private var wifiPassword = ""
    @State private var showingIPSettings = false
    @State private var wifiDHCPSelection = true
    @State private var staticIP = ""
    @State private var staticMask = "255.255.255.0"
    @State private var staticGateway = ""
    @State private var staticDNS = ""
    @State private var showWiFiPassword = false
    @State private var previewOnly = false
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
    @State private var drinks: [DrinkItem] = ContentView.loadDrinks()
    @State private var newDrinkName = ""
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
    @State private var previewPage = 0
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
    // Drinks Mode only: theme-tinted alternating row panels for better contrast.
    // Message Mode and the light speech bubble remain unchanged.
    private func lcdRowBackground(_ index: Int) -> some View {
        ZStack {
            Color(white: index.isMultiple(of: 2) ? 0.13 : 0.075)
            themeColor.opacity(index.isMultiple(of: 2) ? 0.20 : 0.13)
        }
    }
    @State private var appNotice = ""
    @State private var showingPowerConfirmation = false
    @State private var drinkSyncTask: DispatchWorkItem?
    @State private var autoSyncEnabled = UserDefaults.standard.object(forKey: "autoSyncDrinks") as? Bool ?? true

    private let quickMessages = ["こんにちわ", "乾杯！","CHEERS!", "TEQUILA!", "MORE WINE!", "I WANT CHAMPAGNE!"]
    private let maxDisplayDrinks = 24

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
    private var displayedDrinks: [DrinkItem] { Array(drinks.prefix(maxDisplayDrinks)) }
    private var pageCount: Int { max(1, (displayedDrinks.count + 3) / 4) }
    private var previewDrinks: [DrinkItem] {
        let start = min(previewPage, pageCount - 1) * 4
        return Array(displayedDrinks.dropFirst(start).prefix(4))
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 20) {
                    deviceStatusSection
                    wifiSection
                    VStack(alignment: .leading, spacing: 10) {
                        sectionTitle("DISPLAY MODE")
                        Picker("Display Mode", selection: $mode) {
                            ForEach(DisplayMode.allCases, id: \.self) { item in
                                Text(item.rawValue).tag(item)
                            }
                        }
                        .pickerStyle(.segmented)
                        .onChange(of: mode) { _, selected in
                            guard bluetooth.isConnected && !previewOnly else { return }
                            if selected == .message {
                                bluetooth.sendMessage(message)
                            } else {
                                bluetooth.sendDrinks(displayedDrinks.map { (name: $0.name, count: $0.count) })
                            }
                        }
                    }
                    themeSection
                    displayPreview
                    Toggle("Preview changes before sending", isOn: $previewOnly)
                        .tint(themeColor)
                    if previewOnly {
                        Button("Apply Preview to Device") {
                            if bluetooth.isConnected { restoreAfterConnection() }
                        }
                        .buttonStyle(.borderedProminent)
                        .disabled(!bluetooth.isConnected)
                    }
                    if mode == .message {
                        messageSection
                    } else {
                        drinksSection
                    }
                    characterSection
                    moodSection
                    mascotCustomizationSection
                    displayProfilesSection
                    appearanceSection
                    brightnessSection
                    powerSection
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
        .onChange(of: drinks) { _, _ in
            saveDrinks()
            previewPage = min(previewPage, pageCount - 1)
            scheduleDrinkSync()
        }
        .onChange(of: bluetooth.isConnected) { _, connected in
            // Connecting/reconnecting must never overwrite the running LCD display.
            // Battery telemetry is recovered by BluetoothManager independently.
            if !connected { drinkSyncTask?.cancel(); lastAppliedScheduledBrightness = nil }
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
        .onDisappear { drinkSyncTask?.cancel() }
    }

    // MARK: - Wi-Fi setup and telemetry
    private var wifiSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            sectionTitle("CUTE DISPLAY WI-FI")
            HStack(spacing: 8) {
                Image(systemName: bluetooth.wifiConnected ? "wifi" : "wifi.slash")
                    .foregroundStyle(bluetooth.wifiConnected ? .green : .orange)
                Text(!bluetooth.isConnected ? "Connect Bluetooth to check Wi-Fi" :
                     bluetooth.wifiConnected ? "Wi-Fi connected" : "Wi-Fi disconnected")
                    .font(.subheadline.bold())
                Spacer()
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
            Button("Connect CuteDisplay to Wi-Fi") {
                UserDefaults.standard.set(wifiName, forKey: "cuteWiFiName")
                bluetooth.connectWiFi(ssid: wifiName, password: wifiPassword)
                wifiPassword = ""
            }
            .buttonStyle(.borderedProminent)
            .disabled(!bluetooth.isConnected || wifiName.isEmpty)
            HStack(spacing: 8) {
                Button("Reconnect") { bluetooth.enableWiFi() }
                Button("Disconnect") { bluetooth.disconnectWiFi() }
                Button("Forget", role: .destructive) {
                    bluetooth.forgetWiFi()
                    wifiPassword = ""
                }
            }
            .buttonStyle(.bordered)
            .disabled(!bluetooth.isConnected)
            Divider()
            HStack {
                Button("IP Settings") {
                    wifiDHCPSelection = bluetooth.wifiDHCP
                    showingIPSettings = true
                }

            }
            .buttonStyle(.bordered)
            .disabled(!bluetooth.isConnected)
            Text("The device checks its default gateway automatically. Press the left button on CuteDisplay for full network details.")
                .font(.caption2).foregroundStyle(.secondary)
            Text("Configure while connected by Bluetooth. Credentials remain on the device, and it reconnects after a restart. Status refreshes with battery telemetry (about every 2 seconds).")
                .font(.caption2).foregroundStyle(.secondary)
            Text("Personal Hotspot works when the iPhone exposes a compatible Wi-Fi network. For security, use a trusted network; Wi-Fi setup over BLE is not an end-to-end encrypted provisioning protocol.")
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
                            bluetooth.sendDrinksPayload("L:\(enabled ? bluetooth.lowBatteryThreshold : 0)")
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
                                bluetooth.sendDrinksPayload("L:\(value)")
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
                        powerMetric("Time to empty", batteryStateText == "Discharging" ? (bluetooth.minutesToEmpty.map { "\($0) min" } ?? "—") : "—")
                        powerMetric("Time to full", batteryStateText == "Charging" ? (bluetooth.minutesToFull.map { "\($0) min" } ?? "—") : "—")
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
                Label(bluetooth.rememberedDeviceID == nil ? "No remembered device" : "CuteDisplay remembered", systemImage: "checkmark.shield")
                    .font(.subheadline)
                Spacer()
            }
            Toggle("Automatically reconnect", isOn: Binding(
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
                Image(systemName: "antenna.radiowaves.left.and.right")
                    .foregroundStyle(bluetooth.isConnected ? .green : .orange)
                Text(bluetooth.isSimulator ? "Simulator / Demo Mode" : bluetooth.status)
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
                .disabled(bluetooth.isSendingDrinks)
                Text("Bluetooth reconnection only refreshes battery telemetry; it does not change the current LCD screen.")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
            if !bluetooth.isSimulator {
                Button {
                    if bluetooth.isConnected { bluetooth.disconnect() }
                    else { bluetooth.connect() }
                } label: {
                    Label(bluetooth.isConnected ? "Disconnect" : bluetooth.isScanning ? "Searching..." : "Connect to Display",
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
                if mode == .drinks {
                    Text("PAGE \(min(previewPage + 1, pageCount)) / \(pageCount)")
                        .font(.caption2.bold())
                        .foregroundStyle(.gray)
                }
            }
            ZStack {
                RoundedRectangle(cornerRadius: 14)
                    .fill(lcdBackground)
                if mode == .message {
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
                } else {
                    HStack(spacing: 8) {
                        VStack(spacing: 7) {
                            ForEach(Array(previewDrinks.enumerated()), id: \.element.id) { index, drink in
                                HStack(spacing: 4) {
                                    Text(drink.name.uppercased())
                                        .lineLimit(1)
                                        .minimumScaleFactor(0.5)
                                    Spacer(minLength: 2)
                                    Text("×\(drink.count)")
                                        .foregroundStyle(.white)
                                        .fixedSize()
                                }
                                .font(.system(size: 11, weight: .bold, design: .monospaced))
                                .foregroundStyle(themeColor)
                                .padding(.horizontal, 6)
                                .frame(height: 24)
                                .background(lcdRowBackground(index))
                                .clipShape(RoundedRectangle(cornerRadius: 5))
                            }
                            Spacer(minLength: 0)
                        }
                        .frame(maxWidth: .infinity)
                        if showMascot {
                            VStack(spacing: 4) {
                                Text(selectedMood == .sleepy ? "😴" : selectedCharacter.symbol)
                                    .font(.system(size: 51 * CGFloat(mascotSize) / 100))
                                Text(selectedCharacter.title)
                                    .font(.system(size: 9))
                                    .lineLimit(1)
                                    .minimumScaleFactor(0.5)
                                    .foregroundStyle(themeColor)
                            }
                            .frame(width: mascotPreviewWidth)
                            .frame(maxHeight: .infinity)
                            .background(lcdMascotBackground)
                        }
                    }
                    .padding(10)
                }
            }
            .aspectRatio(320.0 / 170.0, contentMode: .fit)
            .clipped()
            if mode == .drinks && pageCount > 1 {
                HStack(spacing: 12) {
                    Button {
                        previewPage = (previewPage - 1 + pageCount) % pageCount
                    } label: {
                        Label("Previous", systemImage: "chevron.left")
                    }
                    Spacer()
                    Text("LCD cycles pages every 3.5 seconds")
                        .font(.caption2)
                        .foregroundStyle(.gray)
                    Spacer()
                    Button {
                        previewPage = (previewPage + 1) % pageCount
                    } label: {
                        Label("Next", systemImage: "chevron.right")
                    }
                }
                .font(.caption)
                .buttonStyle(.bordered)
            }
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

    // MARK: Message mode

    private var messageSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            sectionTitle("MESSAGE")
            Toggle("Speech bubble mode", isOn: $speechBubbleEnabled)
                .tint(.pink)
                .onChange(of: speechBubbleEnabled) { _, enabled in
                    UserDefaults.standard.set(enabled, forKey: "speechBubbleEnabled")
                    if shouldAutoSend { bluetooth.sendDrinksPayload("Q:\(enabled ? 1 : 0)") }
                }
            if speechBubbleEnabled {
                Toggle("Typewriter animation", isOn: $speechTypewriter)
                    .tint(.pink)
                    .onChange(of: speechTypewriter) { _, enabled in
                        UserDefaults.standard.set(enabled, forKey: "speechTypewriter")
                        if shouldAutoSend { bluetooth.sendDrinksPayload("Y:\(enabled ? 1 : 0)") }
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

    // MARK: Drinks mode

    private var drinksSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                sectionTitle("YOUR DRINKS")
                Spacer()
                Text("\(drinks.count) saved · \(min(drinks.count, maxDisplayDrinks)) on LCD")
                    .font(.caption2)
                    .foregroundStyle(.gray)
            }
            ForEach($drinks) { $drink in
                HStack(spacing: 9) {
                    TextField("Drink name", text: $drink.name)
                        .textFieldStyle(.roundedBorder)
                    Button {
                        drink.count = max(0, drink.count - 1)
                    } label: {
                        Image(systemName: "minus.circle.fill").font(.title2)
                    }
                    .tint(themeColor)
                    Text("\(drink.count)").font(.headline).monospacedDigit().frame(minWidth: 25)
                    Button {
                        drink.count = min(9999, drink.count + 1)
                    } label: {
                        Image(systemName: "plus.circle.fill").font(.title2)
                    }
                    .tint(.mint)
                    Button { deleteDrink(id: drink.id) } label: {
                        Image(systemName: "trash")
                    }
                    .tint(.gray)
                }
                .padding(10)
                .background(.white.opacity(0.07))
                .clipShape(RoundedRectangle(cornerRadius: 12))
            }
            sectionTitle("ADD A DRINK")
            HStack(spacing: 10) {
                TextField("New drink name", text: $newDrinkName)
                    .textFieldStyle(.roundedBorder)
                Button { addDrink() } label: {
                    Image(systemName: "plus")
                        .font(.headline)
                        .padding(11)
                        .background(.mint)
                        .foregroundStyle(.black)
                        .clipShape(RoundedRectangle(cornerRadius: 10))
                }
                .disabled(newDrinkName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
            Toggle("Automatically sync drink changes", isOn: $autoSyncEnabled)
                .tint(themeColor)
                .onChange(of: autoSyncEnabled) { _, enabled in
                    UserDefaults.standard.set(enabled, forKey: "autoSyncDrinks")
                    if enabled { scheduleDrinkSync() }
                    else { drinkSyncTask?.cancel() }
                }
            Text(autoSyncEnabled ? "Changes sync automatically after a short pause." : "Tap Update Drinks Display to send changes.")
                .font(.caption2).foregroundStyle(.secondary)
            Text("LCD rotates four drinks per page every 3.5 seconds (up to 24). Japanese names are supported; 12 characters maximum per name.")
                .font(.caption)
                .foregroundStyle(.gray)
            actionButton(bluetooth.isSendingDrinks ? "Sending Drink List..." : "Update Drinks Display", color: .orange) {
                sendDrinks()
            }
            .disabled(!canSend || bluetooth.isSendingDrinks)
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
                    if shouldAutoSend { bluetooth.sendDrinksPayload("S:\(enabled ? 1 : 0)") }
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
                if shouldAutoSend { bluetooth.sendDrinksPayload("A:\(value)") }
            }

            Picker("Held object", selection: $heldObjectMode) {
                Text("Automatic from mood").tag(0)
                Text("Choose manually").tag(1)
            }
            .pickerStyle(.segmented)
            .onChange(of: heldObjectMode) { _, value in
                UserDefaults.standard.set(value, forKey: "cuteHeldObjectMode")
                if shouldAutoSend { bluetooth.sendDrinksPayload("H:\(value)") }
            }

            if heldObjectMode == 1 {
                Picker("Object", selection: $heldObject) {
                    ForEach(0..<objectNames.count, id: \.self) { index in
                        Text(objectNames[index]).tag(index)
                    }
                }
                .onChange(of: heldObject) { _, value in
                    UserDefaults.standard.set(value, forKey: "cuteHeldObject")
                    if shouldAutoSend { bluetooth.sendDrinksPayload("J:\(value)") }
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
                if shouldAutoSend { bluetooth.sendDrinksPayload("K:\(value)") }
            }

            Picker("Animation intensity", selection: $animationIntensity) {
                Text("Subtle").tag(0)
                Text("Normal").tag(1)
                Text("Expressive").tag(2)
            }
            .pickerStyle(.segmented)
            .onChange(of: animationIntensity) { _, value in
                UserDefaults.standard.set(value, forKey: "cuteAnimationIntensity")
                if shouldAutoSend { bluetooth.sendDrinksPayload("I:\(value)") }
            }

            Toggle("Individual mascot personality", isOn: $personalityAnimations)
                .tint(themeColor)
                .onChange(of: personalityAnimations) { _, value in
                    UserDefaults.standard.set(value, forKey: "cutePersonalityAnimations")
                    if shouldAutoSend { bluetooth.sendDrinksPayload("N:\(value ? 1 : 0)") }
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
            name: label, message: message, mode: mode.rawValue,
            theme: selectedTheme, character: selectedCharacter.rawValue,
            mood: selectedMood.rawValue, visible: showMascot,
            mascotSize: mascotSize, accessory: accessoryStyle,
            objectMode: heldObjectMode, heldObject: heldObject,
            frequency: animationFrequency, intensity: animationIntensity,
            personality: personalityAnimations, fontSize: messageFontSize,
            bubble: speechBubbleEnabled, typewriter: speechTypewriter,
            brightness: brightness, drinks: drinks)
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
        // Apply settings locally first; the optional preview mode prevents
        // changing the hardware until the user explicitly taps Apply.
        drinkSyncTask?.cancel()
        message=profile.message
        mode=DisplayMode(rawValue:profile.mode) ?? .message
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
        drinks=profile.drinks
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
                        Text("\(profile.mode) • \(profile.message)")
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
            Text("Save up to 12 profiles on your iPhone. Load applies immediately unless Preview changes before sending is enabled.")
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
            if mode == .message {
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
                Text("Only Message Mode text changes size; drink-row fonts stay unchanged.")
                    .font(.caption)
                    .foregroundStyle(.gray)
            }
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
            .disabled(!bluetooth.isConnected || bluetooth.isSimulator || bluetooth.isSendingDrinks)
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

    private func addDrink() {
        let name = newDrinkName.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty else { return }
        drinks.append(DrinkItem(name: name, count: 0))
        newDrinkName = ""
    }

    private func deleteDrink(id: UUID) { drinks.removeAll { $0.id == id } }

    private func sendDrinks() {
        guard canSend else { appNotice = "Connect to CuteDisplay first"; return }
        bluetooth.sendDrinks(displayedDrinks.map { (name: $0.name, count: $0.count) })
        appNotice = bluetooth.isSimulator
            ? "Simulator preview only; no Bluetooth data sent."
            : "Sending list; wait until Device Status reports completion."
    }

    private func scheduleDrinkSync() {
        drinkSyncTask?.cancel()
        guard autoSyncEnabled, bluetooth.isConnected, !previewOnly else { return }
        let task = DispatchWorkItem { [self] in
            bluetooth.sendDrinks(displayedDrinks.map { (name: $0.name, count: $0.count) })
        }
        drinkSyncTask = task
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.7, execute: task)
    }

    // Reapply the saved preferences only when explicitly requested, for example
    // after a firmware restart that reset the board defaults.
    private func restoreAfterConnection() {
        drinkSyncTask?.cancel()
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
            modeIsDrinks: mode == .drinks,
            message: message,
            drinks: displayedDrinks.map { (name: $0.name, count: $0.count) }
        )
        bluetooth.sendDrinksPayload("L:\(bluetooth.lowBatteryAlertsEnabled ? bluetooth.lowBatteryThreshold : 0)")
        bluetooth.sendDrinksPayload("S:\(surpriseAnimationsEnabled ? 1 : 0)")
        sendMascotCustomization()
        appNotice = "Connected — restoring CuteDisplay settings."
    }

    private func saveDrinks() {
        if let data = try? JSONEncoder().encode(drinks) {
            UserDefaults.standard.set(data, forKey: "savedDrinks")
        }
    }

    private static func loadDrinks() -> [DrinkItem] {
        if let data = UserDefaults.standard.data(forKey: "savedDrinks"),
           let saved = try? JSONDecoder().decode([DrinkItem].self, from: data) {
            return saved
        }
        return [
            DrinkItem(name: "Tequila", count: 9),
            DrinkItem(name: "Wine", count: 2),
            DrinkItem(name: "Champagne", count: 1),
            DrinkItem(name: "Beer", count: 3)
        ]
    }
}

#Preview {
    ContentView()
}