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

struct ContentView: View {
    @StateObject private var bluetooth = BluetoothManager()
    @State private var mode: DisplayMode = .message
    @State private var message = UserDefaults.standard.string(forKey: "savedMessage") ?? "こんにちわ"
    @State private var brightness = 75.0
    @State private var drinks: [DrinkItem] = ContentView.loadDrinks()
    @State private var newDrinkName = ""
    @State private var selectedCharacter = CuteCharacter(
        rawValue: UserDefaults.standard.object(forKey: "selectedCharacter") as? Int ?? 1
    ) ?? .kitty
    @State private var showMascot = UserDefaults.standard.object(forKey: "showMascot") as? Bool ?? true
    @State private var selectedMood = CuteMood(rawValue: UserDefaults.standard.integer(forKey: "mascotMood")) ?? .happy
    @State private var mascotSize = UserDefaults.standard.object(forKey: "mascotSize") as? Int ?? 100
    @State private var messageFontSize = UserDefaults.standard.object(forKey: "messageFontSize") as? Int ?? 3
    @State private var previewPage = 0
    @State private var selectedTheme = UserDefaults.standard.integer(forKey: "displayTheme")
    private let themeNames = [
        "Pink", "Cyan", "Mint", "Yellow", "Lavender",
        "Rose", "Ocean", "Peach", "Lime", "Ruby",
        "Ice", "Sunset", "Lilac", "Gold", "Sky"
    ]
    private let themeColors: [Color] = [
        Color(red: 1, green: 0.35, blue: 0.75), .cyan, .green, .yellow, .purple,
        Color(red: 1, green: 0.48, blue: 0.62), .blue,
        Color(red: 1, green: 0.70, blue: 0.47), .green, .red,
        Color(red: 0.73, green: 0.95, blue: 1), .orange,
        Color(red: 0.82, green: 0.51, blue: 1),
        Color(red: 1, green: 0.80, blue: 0.28),
        Color(red: 0.36, green: 0.75, blue: 1)
    ]
    private var themeColor: Color { themeColors[min(14, max(0, selectedTheme))] }
    private var lcdBackground: Color {
        let backgrounds: [Color] = [
            .black, Color(red: 0,green: 0.02,blue: 0.18),
            Color(red: 0,green: 0.10,blue: 0.05),
            Color(red: 0.17,green: 0.10,blue: 0),
            Color(red: 0.13,green: 0.02,blue: 0.17),
            Color(red: 0.14,green: 0.01,blue: 0.05),
            Color(red: 0,green: 0.01,blue: 0.16),
            Color(red: 0.16,green: 0.02,blue: 0.02),
            Color(red: 0.05,green: 0.10,blue: 0),
            Color(red: 0.13,green: 0,blue: 0.02),
            Color(red: 0,green: 0.02,blue: 0.05),
            Color(red: 0.16,green: 0.02,blue: 0.02),
            Color(red: 0.12,green: 0.01,blue: 0.12),
            Color(red: 0.15,green: 0.10,blue: 0),
            Color(red: 0,green: 0.04,blue: 0.13)
        ]
        return backgrounds[min(14,max(0,selectedTheme))]
    }
    private var lcdMascotBackground: Color { .black }
    private var mascotPreviewWidth: CGFloat { showMascot ? CGFloat(max(40, 98 * mascotSize / 100)) * 0.9 : 0 }
    private func lcdRowBackground(_ index: Int) -> Color {
        themeColor.opacity(index.isMultiple(of: 2) ? 0.12 : 0.20)
    }
    @State private var appNotice = ""
    @State private var showingPowerConfirmation = false
    @State private var drinkSyncTask: DispatchWorkItem?
    @State private var autoSyncEnabled = UserDefaults.standard.object(forKey: "autoSyncDrinks") as? Bool ?? true

    private let quickMessages = ["こんにちわ", "乾杯！","CHEERS!", "TEQUILA!", "MORE WINE!", "I WANT CHAMPAGNE!"]
    private let maxDisplayDrinks = 24

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
                    VStack(alignment: .leading, spacing: 10) {
                        sectionTitle("DISPLAY MODE")
                        Picker("Display Mode", selection: $mode) {
                            ForEach(DisplayMode.allCases, id: \.self) { item in
                                Text(item.rawValue).tag(item)
                            }
                        }
                        .pickerStyle(.segmented)
                    }
                    themeSection
                    displayPreview
                    if mode == .message {
                        messageSection
                    } else {
                        drinksSection
                    }
                    characterSection
                    moodSection
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
            if connected { restoreAfterConnection() }
            else { drinkSyncTask?.cancel() }
        }
        .onChange(of: message) { _, value in
            UserDefaults.standard.set(value, forKey: "savedMessage")
        }
        .onDisappear { drinkSyncTask?.cancel() }
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
            Divider()
            HStack(spacing: 8) {
                Image(systemName: "antenna.radiowaves.left.and.right")
                    .foregroundStyle(bluetooth.isConnected ? .green : .orange)
                Text(bluetooth.isSimulator ? "Simulator / Demo Mode" : bluetooth.status)
                    .font(.subheadline)
                    .lineLimit(3)
                Spacer()
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
                            .foregroundStyle(themeColor)
                            .lineLimit(2)
                            .minimumScaleFactor(0.5)
                            .multilineTextAlignment(.center)
                            .frame(maxWidth: .infinity)
                        if showMascot {
                            Text(selectedMood == .sleepy ? "😴" : selectedCharacter.symbol)
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
                        if canSend { bluetooth.setTheme(index) }
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
                        if canSend { bluetooth.sendMessage(text) }
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
                        if canSend { bluetooth.sendMessage("C:\(character.rawValue)") }
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
                        if canSend { bluetooth.sendMessage("M:\(mood.rawValue)") }
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
            Text("Expressions animate on the device, even without an active Bluetooth connection.")
                .font(.caption).foregroundStyle(.secondary)
        }
    }

    // MARK: - Character visibility, size and Message Mode font
    private var appearanceSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            sectionTitle("DISPLAY APPEARANCE")
            Toggle("Show character", isOn: $showMascot)
                .tint(themeColor)
                .onChange(of: showMascot) { _, value in
                    UserDefaults.standard.set(value, forKey: "showMascot")
                    if canSend { bluetooth.sendMessage("V:\(value ? 1 : 0)") }
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
                    if canSend { bluetooth.sendMessage("Z:\(value)") }
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
                        if canSend { bluetooth.sendMessage("F:\(messageFontSize)") }
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
            Slider(value: $brightness, in: 5...100, step: 5) { editing in
                if !editing && canSend { bluetooth.setBrightness(Int(brightness)) }
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
        guard autoSyncEnabled, bluetooth.isConnected else { return }
        let task = DispatchWorkItem { [self] in
            bluetooth.sendDrinks(displayedDrinks.map { (name: $0.name, count: $0.count) })
        }
        drinkSyncTask = task
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.7, execute: task)
    }

    private func restoreAfterConnection() {
        drinkSyncTask?.cancel()
        bluetooth.restoreState(
            theme: selectedTheme,
            character: selectedCharacter.rawValue,
            mood: selectedMood.rawValue,
            visible: showMascot,
            size: mascotSize,
            font: messageFontSize,
            brightness: Int(brightness),
            modeIsDrinks: mode == .drinks,
            message: message,
            drinks: displayedDrinks.map { (name: $0.name, count: $0.count) }
        )
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