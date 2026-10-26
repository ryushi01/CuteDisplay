import Foundation
import CoreBluetooth
import Network
import AccessorySetupKit
import Combine
import UIKit
import UserNotifications

struct CuteAuthorizedAccessory: Identifiable {
    let id: String
    let title: String
}

final class BluetoothManager: NSObject, ObservableObject {
    @Published var isConnected = false
    @Published var wifiFallbackConnected = false
    private var lanConnection: NWConnection?
    private var lanBytes = Data()
    private var lanTimer: Timer?
    private var lanLastAttempt: Date = .distantPast
    private var lanAuthenticated = false
    private var lanCommandInFlight = false
    private var lanToken: String? = UserDefaults.standard.string(forKey: "cuteLanToken")
    private var lanIP: String = UserDefaults.standard.string(forKey: "cuteLanIP") ?? ""
    @Published var isScanning = false
    @Published var status = "Starting Bluetooth..."
    @Published var brightness = 75
    @Published var batteryLevel: Int? = nil
    @Published var batteryVoltage: Double?
    @Published var wifiConnected = false
    @Published var networkDetailsAvailable = false
    @Published var wifiIP = "—"
    @Published var wifiMask = "—"
    @Published var wifiGateway = "—"
    @Published var wifiDNS = "—"
    @Published var wifiRSSI = 0
    @Published var wifiSSID = ""
    @Published var pingResult = "Not tested"
    @Published var pingInProgress = false
    private var ssidFragments: [Int: [UInt8]] = [:]
    private var networkCharacteristic: CBCharacteristic?
    private var networkRefreshStarted = false
    @Published var wifiDHCP = true
    @Published var batteryCurrent: Double?
    @Published var batteryTemperature: Int?
    @Published var batteryHealth: Int?
    @Published var minutesToEmpty: Int?
    @Published var minutesToFull: Int?
    @Published var lastPowerUpdate: Date?
    @Published var autoReconnect = UserDefaults.standard.object(forKey: "cuteAutoReconnect") as? Bool ?? true
    @Published var rememberedDeviceID = UserDefaults.standard.string(forKey: "cutePeripheralID")
    // Explicit accessory choice preserves the LILYGO as a recovery option.
    @Published var authorizedDevices: [CuteAuthorizedAccessory] = []
    @Published var lowBatteryAlertsEnabled = UserDefaults.standard.object(forKey: "cuteLowBatteryAlerts") as? Bool ?? false
    @Published var lowBatteryThreshold = UserDefaults.standard.object(forKey: "cuteLowBatteryThreshold") as? Int ?? 20
    private var lowBatteryAlertArmed = true
    private var lastLowBatteryNotice: Date? = UserDefaults.standard.object(forKey: "cuteLastLowBatteryAlert") as? Date


    private var central: CBCentralManager?
    private let accessorySession = ASAccessorySession()
    private var accessorySessionReady = false
    private var pendingAccessory: ASAccessory?
    @Published var nativePairingAvailable = true
    private var peripheral: CBPeripheral?
    private var commandCharacteristic: CBCharacteristic?
    private let controlServiceUUID = CBUUID(string: "FFF0")
    private let commandUUID = CBUUID(string: "FFF1")
    private let batteryServiceUUID = CBUUID(string: "180F")
    private let batteryLevelUUID = CBUUID(string: "2A19")
    private let powerServiceUUID = CBUUID(string: "FFF3")
    private let powerCharacteristicUUID = CBUUID(string: "FFF4")
    private let networkServiceUUID = CBUUID(string: "FFF5")
    private let networkCharacteristicUUID = CBUUID(string: "FFF6")
    private var intentionalDisconnect = false
    private var restoredPeripherals: [CBPeripheral] = []

    // Keep BLE writes serialized so message, glyph and settings commands preserve order.
    private var pendingCommands: [String] = []
    private var waitingForWrite = false

    var isSimulator: Bool {
        #if targetEnvironment(simulator)
        true
        #else
        false
        #endif
    }

    override init() {
        super.init()
        // Local-network fallback is foreground/best-effort; iOS may suspend sockets.
        lanTimer = Timer.scheduledTimer(withTimeInterval: 4.0, repeats: true) { [weak self] _ in
            self?.maintainLAN()
            self?.pollLANStatus()
        }
        // Show the low-battery banner even while the CuteDisplay screen is visible.
        UNUserNotificationCenter.current().delegate = self
        accessorySession.activate(on: .main) { [weak self] event in
            self?.handleAccessoryEvent(event)
        }
        // Do not instantiate CBCentralManager before native accessory authorization.
    }

    // Local alerts are driven by actual BLE notifications, not by a timer
    // pretending the app can execute continuously while force-closed.
    func setLowBatteryAlerts(_ enabled: Bool) {
        lowBatteryAlertsEnabled = enabled
        UserDefaults.standard.set(enabled, forKey: "cuteLowBatteryAlerts")
        if enabled {
            UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .badge, .sound]) { [weak self] granted, _ in
                DispatchQueue.main.async {
                    if !granted {
                        self?.lowBatteryAlertsEnabled = false
                        UserDefaults.standard.set(false, forKey: "cuteLowBatteryAlerts")
                        self?.status = "Enable CuteDisplay notifications in iPhone Settings"
                    } else if let level = self?.batteryLevel {
                        self?.checkLowBattery(level)
                    }
                }
            }
        } else {
            UNUserNotificationCenter.current().removePendingNotificationRequests(withIdentifiers: ["cute-low-battery"])
        }
    }

    func setLowBatteryThreshold(_ level: Int) {
        lowBatteryThreshold = min(50, max(5, level))
        UserDefaults.standard.set(lowBatteryThreshold, forKey: "cuteLowBatteryThreshold")
        lowBatteryAlertArmed = true
        if let batteryLevel { checkLowBattery(batteryLevel) }
    }

    private func checkLowBattery(_ level: Int) {
        guard (0...100).contains(level) else { return }
        if level >= lowBatteryThreshold + 5 {
            lowBatteryAlertArmed = true
            return
        }
        guard lowBatteryAlertsEnabled, level <= lowBatteryThreshold,
              lowBatteryAlertArmed else { return }
        // Avoid repeatedly alerting on reconnects or noisy SOC estimates.
        if let lastLowBatteryNotice,
           Date().timeIntervalSince(lastLowBatteryNotice) < 6 * 3600 { return }
        lowBatteryAlertArmed = false
        lastLowBatteryNotice = Date()
        UserDefaults.standard.set(lastLowBatteryNotice, forKey: "cuteLastLowBatteryAlert")
        let content = UNMutableNotificationContent()
        content.title = "CuteDisplay battery low"
        content.body = "Battery is at \(level)%. Charge your display soon."
        content.sound = .default
        let request = UNNotificationRequest(
            identifier: "cute-low-battery",
            content: content,
            trigger: nil
        )
        UNUserNotificationCenter.current().add(request)
    }

    // AccessorySetupKit is the authoritative authorization store, not
    // UserDefaults alone. Prefer a still-authorized remembered device.
    private func authorizedIdentifier() -> UUID? {
        let allowed = accessorySession.accessories.compactMap { $0.bluetoothIdentifier }
        if let saved = rememberedDeviceID.flatMap(UUID.init(uuidString:)),
           allowed.contains(saved) { return saved }
        return allowed.first
    }
    private func refreshAuthorizedDevices() {
        authorizedDevices = accessorySession.accessories.compactMap { accessory in
            guard let id = accessory.bluetoothIdentifier else { return nil }
            return CuteAuthorizedAccessory(
                id: id.uuidString,
                title: "\(accessory.displayName) (\(id.uuidString.suffix(4)))"
            )
        }
    }
    func selectAuthorizedDevice(_ selectedID: String) {
        guard let selected = UUID(uuidString: selectedID),
              accessorySession.accessories.contains(where: { $0.bluetoothIdentifier == selected })
        else {
            status = "Device is not authorized. Use Pair New Device first."
            return
        }
        guard selected.uuidString != rememberedDeviceID else { return }
        intentionalDisconnect = true
        if isScanning { central?.stopScan(); isScanning = false }
        stopLANFallback()
        // Credentials below were issued by old C5 firmware; the S3 deliberately
        // has no LAN fallback server, so do not reconnect through the old C5.
        lanToken = nil
        lanIP = ""
        UserDefaults.standard.removeObject(forKey: "cuteLanToken")
        UserDefaults.standard.removeObject(forKey: "cuteLanIP")
        if let current = peripheral { central?.cancelPeripheralConnection(current) }
        clearConnection()
        rememberAuthorized(selected)
        intentionalDisconnect = false
        ensureBluetoothManager()
        startConnection()
    }
    private func handleAccessoryEvent(_ event: ASAccessoryEvent) {
        switch event.eventType {
        case .activated:
            accessorySessionReady = true
            refreshAuthorizedDevices()
            if authorizedIdentifier() == nil { clearRememberedDevice() }
            if let id = authorizedIdentifier() {
                rememberAuthorized(id)
                ensureBluetoothManager()
                recoverRestoredPeripheralIfPossible()
                if autoReconnect { startConnection() }
            }
        case .accessoryAdded, .accessoryChanged:
            pendingAccessory = event.accessory
            refreshAuthorizedDevices()
            if event.eventType == .accessoryChanged, let id = authorizedIdentifier() {
                rememberAuthorized(id)
                ensureBluetoothManager()
                recoverRestoredPeripheralIfPossible()
                if autoReconnect { startConnection() }
            }
        case .pickerDidDismiss:
            refreshAuthorizedDevices()
            if let id = pendingAccessory?.bluetoothIdentifier {
                selectAuthorizedDevice(id.uuidString)
            }
            pendingAccessory = nil
        case .accessoryRemoved:
            refreshAuthorizedDevices()
            if let selected = rememberedDeviceID.flatMap(UUID.init(uuidString:)),
               accessorySession.accessories.contains(where: { $0.bluetoothIdentifier == selected }) {
                return
            }
            intentionalDisconnect = true
            if let peripheral { central?.cancelPeripheralConnection(peripheral) }
            clearConnection()
            clearRememberedDevice()
            if let fallback = authorizedIdentifier() {
                rememberAuthorized(fallback)
                intentionalDisconnect = false
                if autoReconnect { startConnection() }
            } else {
                status = "Accessory removed in iOS settings"
            }
        default:
            break
        }
    }
    private func ensureBluetoothManager() {
        guard central == nil, authorizedIdentifier() != nil else { return }
        central = CBCentralManager(
            delegate: self,
            queue: .main,
            options: [CBCentralManagerOptionRestoreIdentifierKey: "online.classic-ragnarok.CuteDisplay.central"]
        )
    }
    private func recoverRestoredPeripheralIfPossible() {
        guard let id = authorizedIdentifier(),
              let restored = restoredPeripherals.first(where: { $0.identifier == id }) else { return }
        restoredPeripherals.removeAll()
        adoptPeripheral(restored)
    }

    private func adoptPeripheral(_ device: CBPeripheral) {
        peripheral = device
        device.delegate = self
        if device.state == .connected {
            status = "Restoring connected CuteDisplay..."
            discoverOrRestoreServices(on: device)
        } else if autoReconnect && !intentionalDisconnect {
            status = "Reconnecting to saved CuteDisplay..."
            central?.connect(device, options: nil)
        }
    }

    private func discoverOrRestoreServices(on device: CBPeripheral) {
        // A restored CBPeripheral can already have cached GATT services. Re-enumerate
        // their characteristics and resubscribe before treating telemetry as live.
        guard device.state == .connected else { return }
        // A cached connection may predate the FFF5 Wi-Fi service.
        // Always ask CoreBluetooth to discover the full current service set.
        // Reusing device.services alone can permanently hide new services.
        device.discoverServices([controlServiceUUID, batteryServiceUUID,
                                 powerServiceUUID, networkServiceUUID])
    }

    private func inspectServices(on device: CBPeripheral, services: [CBService]) {
        for service in services {
            let uuids: [CBUUID]
            switch service.uuid {
            case controlServiceUUID: uuids = [commandUUID]
            case batteryServiceUUID: uuids = [batteryLevelUUID]
            case powerServiceUUID: uuids = [powerCharacteristicUUID]
            case networkServiceUUID: uuids = [networkCharacteristicUUID]
            default: continue
            }
            if let known = service.characteristics, !known.isEmpty {
                inspectCharacteristics(on: device, service: service, characteristics: known)
            } else {
                device.discoverCharacteristics(uuids, for: service)
            }
        }
    }

    private func inspectCharacteristics(on device: CBPeripheral, service: CBService,
                                        characteristics: [CBCharacteristic]) {
        for characteristic in characteristics {
            if service.uuid == controlServiceUUID && characteristic.uuid == commandUUID {
                commandCharacteristic = characteristic
                isConnected = true
                status = "Connected to CuteDisplay"
                stopLANFallback()
                sendNext()
            } else if service.uuid == networkServiceUUID && characteristic.uuid == networkCharacteristicUUID {
                networkCharacteristic = characteristic
                networkDetailsAvailable = true
                if characteristic.properties.contains(.notify) && !characteristic.isNotifying {
                    device.setNotifyValue(true, for: characteristic)
                } else if characteristic.isNotifying && !networkRefreshStarted {
                    networkRefreshStarted = true
                    refreshNetworkDetails()
                }
                if characteristic.properties.contains(.read) {
                    device.readValue(for: characteristic)
                }
            } else if (service.uuid == powerServiceUUID && characteristic.uuid == powerCharacteristicUUID)
                        || (service.uuid == batteryServiceUUID && characteristic.uuid == batteryLevelUUID) {
                if characteristic.properties.contains(.notify) && !characteristic.isNotifying {
                    device.setNotifyValue(true, for: characteristic)
                }
                if characteristic.properties.contains(.read) {
                    device.readValue(for: characteristic)
                }
            }
        }
    }

    private func rememberAuthorized(_ id: UUID) {
        rememberedDeviceID = id.uuidString
        UserDefaults.standard.set(rememberedDeviceID, forKey: "cutePeripheralID")
    }
    private func clearRememberedDevice() {
        // Forgetting the accessory must also revoke its saved LAN fallback credentials.
        stopLANFallback()
        lanToken = nil
        lanIP = ""
        UserDefaults.standard.removeObject(forKey: "cuteLanToken")
        UserDefaults.standard.removeObject(forKey: "cuteLanIP")
        rememberedDeviceID = nil
        UserDefaults.standard.removeObject(forKey: "cutePeripheralID")
    }
    func connect() {
        intentionalDisconnect = false
        guard authorizedIdentifier() != nil else { pairNewDevice(); return }
        startConnection()
    }
    func pairNewDevice() {
        guard accessorySessionReady else {
            status = "Accessory setup is starting. Try again."
            return
        }
        let descriptor = ASDiscoveryDescriptor()
        descriptor.bluetoothServiceUUID = controlServiceUUID
        descriptor.bluetoothNameSubstring = "CuteDisplay"
        let item = ASPickerDisplayItem(
            name: "CuteDisplay",
            productImage: UIImage(systemName: "display") ?? UIImage(),
            descriptor: descriptor
        )
        accessorySession.showPicker(for: [item]) { [weak self] error in
            if let error { self?.status = "Accessory setup: \(error.localizedDescription)" }
        }
    }
    func setAutoReconnect(_ enabled: Bool) {
        autoReconnect = enabled
        UserDefaults.standard.set(enabled, forKey: "cuteAutoReconnect")
        if enabled && !isConnected { startConnection() }
        if !enabled {
            stopLANFallback()
            if isScanning { central?.stopScan(); isScanning = false }
            if !bleReady() { isConnected = false }
        }
    }
    // Remove authorization through the system UI, not by only deleting UserDefaults.
    func forgetDevice() {
        guard let id = authorizedIdentifier(),
              let accessory = accessorySession.accessories.first(where: { $0.bluetoothIdentifier == id }) else {
            clearRememberedDevice()
            status = "No paired accessory"
            return
        }
        accessorySession.removeAccessory(accessory) { [weak self] error in
            if let error { self?.status = "Remove failed: \(error.localizedDescription)" }
        }
    }
    private func startConnection() {
        if isSimulator { status = "Simulator / Demo Mode"; return }
        guard accessorySessionReady else { return }
        guard let id = authorizedIdentifier() else {
            status = "Pair CuteDisplay with Apple's accessory picker"
            return
        }
        ensureBluetoothManager()
        guard let central, central.state == .poweredOn else { status = "Bluetooth is starting or not ready"; return }
        guard peripheral == nil && !isScanning else {
            if let peripheral, peripheral.identifier == id && peripheral.state == .connected {
                discoverOrRestoreServices(on: peripheral)
            }
            return
        }
        rememberAuthorized(id)
        if let known = central.retrievePeripherals(withIdentifiers: [id]).first {
            adoptPeripheral(known)
        } else {
            isScanning = true
            status = "Finding paired CuteDisplay..."
            central.scanForPeripherals(withServices: [controlServiceUUID], options: nil)
        }
    }
    func disconnect() {
        intentionalDisconnect = true
        if isScanning { central?.stopScan(); isScanning = false }
        stopLANFallback()
        if let peripheral { central?.cancelPeripheralConnection(peripheral) }
        else { clearConnection(); status = "Disconnected" }
    }

    private func clearConnection() {
        isConnected = wifiFallbackConnected
        isScanning = false
        if !wifiFallbackConnected {
        batteryLevel = nil
        batteryVoltage = nil
        batteryCurrent = nil
        batteryTemperature = nil
        batteryHealth = nil
        minutesToEmpty = nil
        minutesToFull = nil
        lastPowerUpdate = nil
        }
        commandCharacteristic = nil
        networkCharacteristic = nil
        networkDetailsAvailable = false
        networkRefreshStarted = false
        if !wifiFallbackConnected { pendingCommands.removeAll() }
        waitingForWrite = false
        peripheral = nil
        if !wifiFallbackConnected { isConnected = false }
    }

    // Smooth 24x24 glyphs: each pixel uses 2-bit coverage.
    // Sent as four 36-byte chunks to stay within the BLE command limit.
    func sendMessage(_ text: String) {
        guard text.utf8.count <= 96 else {
            status = "Message exceeds 96 UTF-8 bytes"
            return
        }
        enqueue(glyphPackets(for: [text]) + [text])
    }
    func sendControlCommand(_ payload: String) { enqueue([payload]) }
    // Wi-Fi credentials are provisioned over the connected BLE link.
    // Only use a network that you control. Password is never logged.
    func connectWiFi(ssid: String, password: String) {
        let name = ssid.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty && name.utf8.count <= 32,
              password.utf8.count <= 63,
              (password.isEmpty || password.utf8.count >= 8),
              !name.contains("\n"), !password.contains("\n") else {
            status = "Wi-Fi SSID must be 1–32 bytes; password 8–63 bytes (or empty)"
            return
        }
        enqueue(["W:S:\(name)", "W:P:\(password)", "W:C"])
    }

    func configureIP(dhcp: Bool, ip: String, mask: String, gateway: String, dns: String) {
        if dhcp { enqueue(["W:DHCP", "W:INFO"]); return }
        let values = [ip, mask, gateway, dns]
        guard values.allSatisfy({ Self.validIPv4($0) }) else {
            status = "Enter valid IPv4 address, subnet mask, gateway and DNS"
            return
        }
        enqueue(["W:STATIC:" + values.joined(separator: "|"), "W:INFO"])
    }

    private static func validIPv4(_ value: String) -> Bool {
        let parts = value.split(separator: ".", omittingEmptySubsequences: false)
        return parts.count == 4 && parts.allSatisfy {
            !$0.isEmpty && $0.count <= 3 && $0.allSatisfy(\.isNumber)
            && (Int($0).map { (0...255).contains($0) } ?? false)
        }
    }
    func refreshNetworkDetails() {
        // Request one field per acknowledged BLE write instead of relying on
        // a burst of notifications from the ESP32.
        enqueue(["W:GET:KEY","W:GET:LINK","W:GET:MODE","W:GET:IP","W:GET:MASK",
                 "W:GET:GW","W:GET:DNS","W:GET:RSSI","W:GET:SSID"])
    }
    func ping(address: String) {
        let host = address.trimmingCharacters(in: .whitespacesAndNewlines)
        guard Self.validIPv4(host) else {
            pingResult = "Enter a valid IPv4 address"
            return
        }
        pingResult = "Testing \(host)…"
        pingInProgress = true
        enqueue(["W:PING:\(host)"])
        Task { @MainActor [weak self] in
            try? await Task.sleep(for: .seconds(8))
            guard let self, self.pingInProgress else { return }
            self.pingInProgress = false
            self.pingResult = "No ping result received within 8 seconds"
        }
    }
    func disconnectWiFi() { enqueue(["W:OFF"]) }
    func enableWiFi() { enqueue(["W:ON"]) }
    func forgetWiFi() { enqueue(["W:FORGET"]) }

    func configureMascot(accessory: Int, objectMode: Int, object: Int,
                         frequency: Int, intensity: Int, personality: Bool) {
        enqueue(["A:\(accessory)", "H:\(objectMode)", "J:\(object)",
                 "K:\(frequency)", "I:\(intensity)", "N:\(personality ? 1 : 0)"])
    }

    func previewMascotAnimation(_ kind: Int) {
        enqueue(["R:\(min(2, max(0, kind)))"])
    }

    func setTheme(_ index: Int) {
        enqueue(["T:\(min(24,max(0,index)))"])
    }

    private func glyphPackets(for strings: [String]) -> [String] {
        let scalars = Set(strings.joined().unicodeScalars.filter {
            $0.value >= 33 && !$0.properties.isWhitespace
        })
        var packets: [String] = []
        // Firmware retains 48 high-quality glyphs; earlier ones are evicted
        // if more are transferred. Keep transfers bounded.
        for scalar in scalars.sorted(by: { $0.value < $1.value }).prefix(48) {
            guard let bitmap = Self.smoothBitmap(for: scalar) else { continue }
            let cp = String(scalar.value, radix: 16).uppercased()
            for part in 0..<4 {
                let bytes = bitmap[(part * 36)..<((part + 1) * 36)]
                let hex = bytes.map { String(format: "%02X", $0) }.joined()
                packets.append("G2:\(cp):\(part):\(hex)")
            }
        }
        return packets
    }

    // Draw at true 24x24 resolution, preserving antialiased edges.
    // Each group of 4 pixels occupies a single byte (2 bits each).
    private static func smoothBitmap(for scalar: Unicode.Scalar) -> [UInt8]? {
        let side = 24
        var rgb = [UInt8](repeating: 0, count: side * side * 4)
        let ok = rgb.withUnsafeMutableBytes { ptr -> Bool in
            guard let base = ptr.baseAddress,
                  let context = CGContext(
                    data: base, width: side, height: side,
                    bitsPerComponent: 8, bytesPerRow: side * 4,
                    space: CGColorSpaceCreateDeviceRGB(),
                    bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue
                  ) else { return false }
            context.setFillColor(UIColor.black.cgColor)
            context.fill(CGRect(x: 0, y: 0, width: side, height: side))
            UIGraphicsPushContext(context)
            defer { UIGraphicsPopContext() }
            let character = String(scalar) as NSString
            let font = UIFont.systemFont(
                ofSize: scalar.value < 128 ? 21 : 22,
                weight: scalar.value < 128 ? .semibold : .medium
            )
            let attributes: [NSAttributedString.Key: Any] = [
                .font: font,
                .foregroundColor: UIColor.white
            ]
            character.draw(in: CGRect(x: 0, y: -1, width: 24, height: 27),
                           withAttributes: attributes)
            return true
        }
        guard ok else { return nil }
        var packed = [UInt8](repeating: 0, count: 144)
        for y in 0..<24 {
            for x in 0..<24 {
                // CoreGraphics raw bitmap coordinates are bottom-up.
                let off = ((23 - y) * 24 + x) * 4
                let light = (Int(rgb[off]) + Int(rgb[off + 1])
                             + Int(rgb[off + 2])) / 3
                let coverage = UInt8(min(3, (light + 42) / 85))
                let index = y * 24 + x
                packed[index / 4] |= coverage << (6 - 2 * (index % 4))
            }
        }
        return packed
    }

    // Queued after any earlier writes. The board turns its screen off and
    // enters deep sleep; reconnect only after pressing the hardware RESET.
    func powerOff() {
        guard !isSimulator, isConnected else { return }
        enqueue(["P:OFF"])
        status = "Power-off requested — press board RESET to wake"
    }

    func setBrightness(_ value: Int) {
        brightness = min(100, max(0, value))
        enqueue(["B:\(brightness)"])
    }

    // Reapply display preferences and message after reconnect.
    // Commands are queued in order and use Write With Response.
    func restoreState(theme: Int, character: Int, mood: Int,
                      visible: Bool, size: Int, font: Int,
                      bubble: Bool, typewriter: Bool, brightness: Int,
                      message: String) {
        guard isConnected else { return }
        enqueue([
            "T:\(min(24, max(0, theme)))",
            "C:\(min(5, max(0, character)))",
            "M:\(min(7, max(0, mood)))",
            "V:\(visible ? 1 : 0)",
            "Z:\(size)",
            "F:\(font)",
            "Q:\(bubble ? 1 : 0)",
            "Y:\(typewriter ? 1 : 0)",
            "B:\(min(100, max(0, brightness)))"
        ])
        sendMessage(message)
    }

    private func enqueue(_ commands: [String]) {
        if isSimulator { status = "Demo Mode — no Bluetooth sent"; return }
        guard (peripheral != nil && commandCharacteristic != nil && isConnected) || wifiFallbackConnected else {
            status = "Not connected to CuteDisplay"
            return
        }
        guard commands.allSatisfy({ !$0.isEmpty && $0.utf8.count <= 96 }) else {
            status = "Bluetooth command exceeds 96 bytes"
            return
        }
        pendingCommands.append(contentsOf: commands)
        sendNext()
    }

    private func sendNext() {
        guard !waitingForWrite, !pendingCommands.isEmpty else { return }
        if let peripheral, let characteristic = commandCharacteristic, peripheral.state == .connected {
            let next = pendingCommands.removeFirst()
            guard let data = next.data(using: .utf8) else { return }
            waitingForWrite = true
            peripheral.writeValue(data, for: characteristic, type: .withResponse)
        } else if wifiFallbackConnected {
            let next = pendingCommands.removeFirst()
            waitingForWrite = true
            lanConnection?.send(content: Data(("CMD " + next + "\n").utf8),
                                completion: .contentProcessed { [weak self] error in
                if let error { self?.lanFailure(error.localizedDescription) }
            })
        }
    }
}

extension BluetoothManager: CBCentralManagerDelegate {
    // Called if iOS restores a previous BLE central session in the background.
    func centralManager(_ central: CBCentralManager,
                        willRestoreState dict: [String: Any]) {
        restoredPeripherals = dict[CBCentralManagerRestoredStatePeripheralsKey] as? [CBPeripheral] ?? []
        // The accessory authorization event can arrive after this callback.
        // Keep restored peripherals until the system confirms their identity.
        recoverRestoredPeripheralIfPossible()
    }

    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        if isSimulator { status = "Simulator / Demo Mode"; return }
        switch central.state {
        case .poweredOn:
            status = "Ready to connect"
            if autoReconnect && !intentionalDisconnect { startConnection() }
        case .poweredOff: clearConnection(); status = "Turn on Bluetooth"
        case .unauthorized: clearConnection(); status = "Allow Bluetooth access in Settings"
        case .unsupported: clearConnection(); status = "Bluetooth LE unsupported"
        default: status = "Bluetooth unavailable"
        }
    }

    func centralManager(_ central: CBCentralManager,
                        didDiscover found: CBPeripheral,
                        advertisementData: [String: Any], rssi RSSI: NSNumber) {
        guard peripheral == nil else { return }
        guard let id = authorizedIdentifier(), found.identifier == id else { return }
        central.stopScan()
        isScanning = false
        peripheral = found
        found.delegate = self
        status = "Connecting..."
        central.connect(found, options: nil)
    }

    func centralManager(_ central: CBCentralManager, didConnect device: CBPeripheral) {
        guard device.identifier == authorizedIdentifier() else {
            central.cancelPeripheralConnection(device)
            return
        }
        rememberAuthorized(device.identifier)
        status = "Discovering services..."
        discoverOrRestoreServices(on: device)
    }

    func centralManager(_ central: CBCentralManager,
                        didFailToConnect device: CBPeripheral, error: Error?) {
        clearConnection()
        status = error?.localizedDescription ?? "Connection failed"
        if autoReconnect && !intentionalDisconnect { startConnection() }
    }

    func centralManager(_ central: CBCentralManager,
                        didDisconnectPeripheral device: CBPeripheral, error: Error?) {
        // Ignore a late callback from the previous accessory after switching.
        guard peripheral?.identifier == device.identifier else { return }
        clearConnection()
        status = error == nil ? "Disconnected" : "Disconnected: \(error!.localizedDescription)"
        if autoReconnect && !intentionalDisconnect { startConnection() }
    }
}

extension BluetoothManager: CBPeripheralDelegate {
    func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
        if let error { status = "Service error: \(error.localizedDescription)"; return }
        guard let services = peripheral.services else { return }
        inspectServices(on: peripheral, services: services)
    }

    func peripheral(_ peripheral: CBPeripheral,
                    didDiscoverCharacteristicsFor service: CBService, error: Error?) {
        if let error { status = "Characteristic error: \(error.localizedDescription)"; return }
        inspectCharacteristics(on: peripheral, service: service,
                               characteristics: service.characteristics ?? [])
    }

    func peripheral(_ peripheral: CBPeripheral,
                    didUpdateNotificationStateFor characteristic: CBCharacteristic,
                    error: Error?) {
        guard characteristic.uuid == networkCharacteristicUUID else { return }
        if let error {
            status = "Wi-Fi detail subscription failed: \(error.localizedDescription)"
            return
        }
        if characteristic.isNotifying && !networkRefreshStarted {
            networkRefreshStarted = true
            refreshNetworkDetails()
        }
    }

    func peripheral(_ peripheral: CBPeripheral,
                    didUpdateValueFor characteristic: CBCharacteristic, error: Error?) {
        if characteristic.uuid == networkCharacteristicUUID {
            guard error == nil, let data = characteristic.value,
                  let value = String(data: data, encoding: .utf8),
                  value.hasPrefix("N:") else { return }
            let fields = value.split(separator: ":", maxSplits: 3,
                                     omittingEmptySubsequences: false).map(String.init)
            guard fields.count >= 2 else { return }
            switch fields[1] {
            case "LINK":
                if fields.count > 2 { wifiConnected = fields[2] == "1" }
            case "MODE":
                if fields.count > 2 { wifiDHCP = fields[2] == "DHCP" }
            case "IP":
                if fields.count > 2 {
                    wifiIP = fields[2]
                    if Self.validIPv4(fields[2]) {
                        lanIP = fields[2]
                        UserDefaults.standard.set(lanIP, forKey: "cuteLanIP")
                    }
                }
            case "KEY":
                if fields.count > 2, fields[2].count == 32,
                   fields[2].allSatisfy({ $0.isHexDigit }) {
                    lanToken = fields[2]
                    UserDefaults.standard.set(fields[2], forKey: "cuteLanToken")
                }
            case "MASK": if fields.count > 2 { wifiMask = fields[2] }
            case "GW": if fields.count > 2 { wifiGateway = fields[2] }
            case "DNS": if fields.count > 2 { wifiDNS = fields[2] }
            case "RSSI": if fields.count > 2 { wifiRSSI = Int(fields[2]) ?? 0 }
            case let name where name.hasPrefix("S") && name.dropFirst().allSatisfy(\.isNumber):
                if fields.count > 2, let index = Int(name.dropFirst()) {
                    if index == 0 { ssidFragments.removeAll() }
                    let hex = fields[2]
                    if hex.count.isMultiple(of: 2) {
                        var bytes: [UInt8] = []
                        var cursor = hex.startIndex
                        while cursor < hex.endIndex {
                            let end = hex.index(cursor, offsetBy: 2)
                            if let byte = UInt8(hex[cursor..<end], radix: 16) {
                                bytes.append(byte)
                            }
                            cursor = end
                        }
                        ssidFragments[index] = bytes
                    }
                }
            case "END":
                let bytes = (0..<6).flatMap { ssidFragments[$0] ?? [] }
                wifiSSID = String(decoding: bytes, as: UTF8.self)
            case "PING":
                if fields.count > 2 {
                    pingInProgress = false
                    switch fields[2] {
                    case "OK":
                        pingResult = fields.count > 3 ? "Reply received in \(fields[3]) ms" : "Reply received"
                    case "TIMEOUT": pingResult = "Timed out (no ICMP echo reply)"
                    case "NO_WIFI": pingResult = "CuteDisplay Wi-Fi disconnected"
                    case "INVALID": pingResult = "Invalid IP address"
                    default: pingResult = "Ping failed: \(fields[2])"
                    }
                }
            default: break
            }
            return
        }
        if characteristic.uuid == powerCharacteristicUUID {
            guard error == nil, let data = characteristic.value,
                  let string = String(data: data, encoding: .utf8) else { return }
            let f = string.split(separator: ",")
            guard f.count >= 7, let level = Int(f[0]), let voltage = Double(f[1]),
                  let current = Double(f[2]), let temperature = Int(f[3]),
                  let health = Int(f[4]), let empty = Int(f[5]), let full = Int(f[6]),
                  (0...100).contains(level), voltage > 0 else { return }
            if f.count >= 8 { wifiConnected = (f[7] == "1") }
            batteryLevel = level
            checkLowBattery(level)
            batteryVoltage = voltage
            batteryCurrent = current
            batteryTemperature = temperature
            batteryHealth = health
            minutesToEmpty = empty
            minutesToFull = full
            lastPowerUpdate = Date()
            return
        }
        guard characteristic.uuid == batteryLevelUUID else { return }
        if error != nil { batteryLevel = nil; return }
        if let data = characteristic.value, data.count == 1,
           let level = data.first, level <= 100 {
            batteryLevel = Int(level)
            checkLowBattery(Int(level))
        } else {
            batteryLevel = nil
        }
    }

    func peripheral(_ peripheral: CBPeripheral,
                    didWriteValueFor characteristic: CBCharacteristic, error: Error?) {
        commandCompleted(errorMessage: error?.localizedDescription)
    }

    private func commandCompleted(errorMessage: String?) {
        waitingForWrite = false
        if let errorMessage {
            pendingCommands.removeAll()
            status = "Send failed: \(errorMessage)"
            return
        }
        sendNext()
    }

    // Wi-Fi fallback: connects only to a previously provisioned, reachable LAN IP.
    // No automatic enabling of the ESP32 Wi-Fi radio or cloud service.
    private func bleReady() -> Bool {
        peripheral?.state == .connected && commandCharacteristic != nil
    }

    private func maintainLAN() {
        // Phase-3 S3 owns WiFi; the old C5 TCP/8848 fallback is disabled.
        // Never reuse the saved C5 LAN token/IP when switching accessories.
        return
        if bleReady() {
            if wifiFallbackConnected { stopLANFallback() }
            return
        }
        guard autoReconnect, !intentionalDisconnect,
              !wifiFallbackConnected, lanConnection == nil,
              let token = lanToken, token.count == 32,
              Self.validIPv4(lanIP),
              Date().timeIntervalSince(lanLastAttempt) >= 8 else { return }
        lanLastAttempt = Date()
        guard let port = NWEndpoint.Port(rawValue: 8848) else { return }
        let conn = NWConnection(host: NWEndpoint.Host(lanIP), port: port, using: .tcp)
        lanConnection = conn
        lanAuthenticated = false
        lanBytes.removeAll()
        conn.stateUpdateHandler = { [weak self, weak conn] state in
            guard let self, let conn, self.lanConnection === conn else { return }
            switch state {
            case .ready:
                guard let token = self.lanToken else { return }
                conn.send(content: Data(("AUTH " + token + "\n").utf8),
                          completion: .contentProcessed { [weak self] error in
                    if let error { self?.lanFailure(error.localizedDescription) }
                })
                self.receiveLAN(conn)
            case .failed(let error): self.lanFailure(error.localizedDescription)
            case .cancelled: break
            default: break
            }
        }
        conn.start(queue: .main)
    }

    private func receiveLAN(_ connection: NWConnection) {
        connection.receive(minimumIncompleteLength: 1, maximumLength: 1024) { [weak self, weak connection] data, _, complete, error in
            guard let self, let connection, self.lanConnection === connection else { return }
            if let data { self.lanBytes.append(data) }
            while let newline = self.lanBytes.firstIndex(of: 10) {
                let line = String(decoding: self.lanBytes.prefix(upTo: newline), as: UTF8.self)
                self.lanBytes.removeSubrange(...newline)
                self.handleLANLine(line.trimmingCharacters(in: .whitespacesAndNewlines))
            }
            if complete || error != nil { self.lanFailure(error?.localizedDescription ?? "Connection closed") }
            else { self.receiveLAN(connection) }
        }
    }

    private func handleLANLine(_ line: String) {
        if line == "OK" {
            lanAuthenticated = true
            wifiFallbackConnected = true
            isConnected = true
            status = "Connected over Wi-Fi (Bluetooth unavailable)"
            sendNext()
        } else if line == "ACK" {
            commandCompleted(errorMessage: nil)
        } else if line == "NACK" || line == "DENIED" {
            if line == "DENIED" { lanFailure("Wi-Fi authentication failed; reconnect with Bluetooth") }
            else { commandCompleted(errorMessage: "Command rejected over Wi-Fi") }
        } else if line.hasPrefix("S:") {
            let f = line.dropFirst(2).split(separator: ",")
            guard f.count >= 8, let level = Int(f[0]),
                  let voltage = Double(f[1]), let current = Double(f[2]),
                  let temperature = Int(f[3]), let health = Int(f[4]),
                  let empty = Int(f[5]), let full = Int(f[6]),
                  (0...100).contains(level), voltage > 0 else { return }
            batteryLevel = level
            checkLowBattery(level)
            batteryVoltage = voltage
            batteryCurrent = current
            batteryTemperature = temperature
            batteryHealth = health
            minutesToEmpty = empty
            minutesToFull = full
            lastPowerUpdate = Date()
            wifiConnected = f[7] == "1"
        }
    }

    private func stopLANFallback() {
        lanConnection?.stateUpdateHandler = nil
        lanConnection?.cancel()
        lanConnection = nil
        lanAuthenticated = false
        wifiFallbackConnected = false
        lanBytes.removeAll()
    }

    private func lanFailure(_ reason: String) {
        guard lanConnection != nil else { return }
        stopLANFallback()
        waitingForWrite = false
        isConnected = bleReady()
        if !isConnected { status = "Wi-Fi fallback unavailable: " + reason }
    }

    private func pollLANStatus() {
        guard wifiFallbackConnected, !bleReady() else { return }
        lanConnection?.send(content: Data("STATUS\n".utf8), completion: .contentProcessed { [weak self] error in
            if let error { self?.lanFailure(error.localizedDescription) }
        })
    }

}
extension BluetoothManager: UNUserNotificationCenterDelegate {
    func userNotificationCenter(_ center: UNUserNotificationCenter,
                                willPresent notification: UNNotification,
                                withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([.banner, .list, .sound])
    }
}
