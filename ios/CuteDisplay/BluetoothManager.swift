import Foundation
import CoreBluetooth
import Network
import CryptoKit
import Security
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
    @Published var bluetoothBrainConnected = false
    @Published var wifiFallbackConnected = false
    private var lanConnection: NWConnection?
    private var lanBytes = Data()
    private var lanTimer: Timer?
    private var lanLastAttempt: Date = .distantPast
    private var lanAuthenticated = false
    private var lanCommandInFlight = false
    private var lanToken: String?
    private var lanIP = ""
    private var lanBrowser: NWBrowser?
    private var brainServiceEndpoint: NWEndpoint?
    private var lanLastReply = Date.distantPast
    private var nextBLEAttempt = Date.distantPast
    private var bleConnectStarted = Date.distantPast
    private var bleRecoveryAttempts = 0
    private var brainBLEReady = false
    @Published var isScanning = false
    @Published var status = "Starting Bluetooth..."
    @Published var aiLiveStatus = "Idle"
    @Published var brightness = 75
    @Published var batteryLevel: Int? = nil
    @Published var batteryVoltage: Double?
    @Published var wifiConnected = false
    @Published var wifiConnectionState = "OFF"
    @Published var wifiConnectionError = ""
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
    // S3 FFF1 has NOTIFY and acknowledges actual C5 UART completion.
    // The original C5 FFF1 has no NOTIFY and still uses GATT write responses.
    private var awaitingBrainAck = false
    private var brainWriteComplete = false
    private var brainResponse: String?
    private var brainReadyReadAttempts = 0
    private var bleCommandGeneration = 0

    var isSimulator: Bool {
        #if targetEnvironment(simulator)
        true
        #else
        false
        #endif
    }

    override init() {
        super.init()
        // Foreground best-effort; CoreBluetooth restoration handles eligible
        // background reconnects under the operating system's own limits.
        lanTimer = Timer.scheduledTimer(withTimeInterval: 4.0, repeats: true) { [weak self] _ in
            self?.maintainBluetoothReconnect()
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
        // A LAN capability belongs to a specific authorized S3 Brain.
        lanToken = nil
        lanIP = ""
        brainServiceEndpoint = nil
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

    // iOS may notify the user about a background connection/disconnection.
    // These options do not replace local low-battery notifications.
    private var brainConnectionOptions: [String: Any] {
        [CBConnectPeripheralOptionNotifyOnConnectionKey: true,
         CBConnectPeripheralOptionNotifyOnDisconnectionKey: true]
    }
    private func adoptPeripheral(_ device: CBPeripheral) {
        peripheral = device
        bleConnectStarted = Date()
        bleRecoveryAttempts = 0
        device.delegate = self
        if device.state == .connected {
            status = "Restoring connected CuteDisplay..."
            discoverOrRestoreServices(on: device)
        } else if autoReconnect && !intentionalDisconnect {
            status = "Reconnecting to saved CuteDisplay..."
            central?.connect(device, options: brainConnectionOptions)
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
                // Do not subscribe before encryption; that creates a second
                // protected GATT operation while pairing is in flight.
                // Subscribe only when FFF1 reports PROXY_READY below.
                // Service discovery is not BLE security/bonding.
                // A read of encrypted FFF1 triggers pairing on iOS, and the
                // app becomes usable only after didUpdateValueFor succeeds.
                if !brainBLEReady {
                    status = "Securing Bluetooth with the Brain..."
                    if characteristic.properties.contains(.read) {
                        device.readValue(for: characteristic)
                    } else {
                        status = "Brain control characteristic is not readable"
                    }
                }
            } else if service.uuid == networkServiceUUID && characteristic.uuid == networkCharacteristicUUID {
                networkCharacteristic = characteristic
                networkDetailsAvailable = true
                if brainBLEReady {
                    if characteristic.properties.contains(.notify) && !characteristic.isNotifying {
                        device.setNotifyValue(true, for: characteristic)
                    } else if characteristic.isNotifying && !networkRefreshStarted {
                        networkRefreshStarted = true
                        refreshNetworkDetails()
                    }
                    if characteristic.properties.contains(.read) {
                        device.readValue(for: characteristic)
                    }
                }
            } else if (service.uuid == powerServiceUUID && characteristic.uuid == powerCharacteristicUUID)
                        || (service.uuid == batteryServiceUUID && characteristic.uuid == batteryLevelUUID) {
                if brainBLEReady {
                    if characteristic.properties.contains(.notify) && !characteristic.isNotifying {
                        device.setNotifyValue(true, for: characteristic)
                    }
                    if characteristic.properties.contains(.read) {
                        device.readValue(for: characteristic)
                    }
                }
            }
        }
    }

    // Never batch GATT reads and subscriptions while iOS and NimBLE are
    // still negotiating encryption. One protected FFF1 read starts security.
    // After PROXY_READY, restore telemetry and subscribe to command ACKs.
    private func beginBrainDataSubscriptions(on device: CBPeripheral) {
        if let control = commandCharacteristic,
           control.properties.contains(.notify), !control.isNotifying {
            device.setNotifyValue(true, for: control)
        }
        for service in device.services ?? [] where service.uuid != controlServiceUUID {
            if let known = service.characteristics, !known.isEmpty {
                inspectCharacteristics(on: device, service: service, characteristics: known)
            }
        }
    }

    // The LAN key is sent exclusively over encrypted Brain BLE and saved
    // in iOS Keychain, scoped to this authorized accessory's BLE UUID.
    private func brainKeyAccount(_ id: UUID) -> String {
        "CuteDisplay-Brain-LAN-\(id.uuidString)"
    }
    private func removeBrainKey(_ id: UUID) {
        let item: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: "CuteDisplay.BrainLAN",
            kSecAttrAccount as String: brainKeyAccount(id)
        ]
        SecItemDelete(item as CFDictionary)
    }
    private func saveBrainKey(_ hex: String, for id: UUID) {
        guard hex.count == 64, hex.allSatisfy({ $0.isHexDigit }) else { return }
        removeBrainKey(id)
        let item: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: "CuteDisplay.BrainLAN",
            kSecAttrAccount as String: brainKeyAccount(id),
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
            kSecValueData as String: Data(hex.lowercased().utf8)
        ]
        if SecItemAdd(item as CFDictionary, nil) == errSecSuccess {
            lanToken = hex.lowercased()
        }
    }
    private func readBrainKey(_ id: UUID) -> String? {
        let item: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: "CuteDisplay.BrainLAN",
            kSecAttrAccount as String: brainKeyAccount(id),
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne
        ]
        var result: CFTypeRef?
        guard SecItemCopyMatching(item as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data,
              let hex = String(data: data, encoding: .utf8),
              hex.count == 64, hex.allSatisfy({ $0.isHexDigit }) else { return nil }
        return hex
    }
    private func rememberAuthorized(_ id: UUID) {
        rememberedDeviceID = id.uuidString
        UserDefaults.standard.set(rememberedDeviceID, forKey: "cutePeripheralID")
        lanToken = readBrainKey(id)
        lanIP = UserDefaults.standard.string(forKey: "cuteBrainIP.\(id.uuidString)") ?? ""
        // Old C5 LAN credentials must never be used to authenticate to S3.
        UserDefaults.standard.removeObject(forKey: "cuteLanToken")
    }
    private func clearRememberedDevice() {
        stopLANFallback()
        if let id = rememberedDeviceID.flatMap(UUID.init(uuidString:)) {
            removeBrainKey(id)
            UserDefaults.standard.removeObject(forKey: "cuteBrainIP.\(id.uuidString)")
        }
        lanToken = nil
        lanIP = ""
        rememberedDeviceID = nil
        UserDefaults.standard.removeObject(forKey: "cutePeripheralID")
        UserDefaults.standard.removeObject(forKey: "cuteLanToken")
        UserDefaults.standard.removeObject(forKey: "cuteLanIP")
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
        if enabled && !bleReady() { startConnection() }
        if !enabled {
            // This setting controls Bluetooth reconnect only. Authenticated
            // Brain LAN fallback can remain online if the user chooses.
            if isScanning { central?.stopScan(); isScanning = false }
            if !wifiFallbackConnected && !bleReady() { isConnected = false }
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
    private func maintainBluetoothReconnect() {
        guard autoReconnect, !intentionalDisconnect, accessorySessionReady,
              authorizedIdentifier() != nil, !bleReady(),
              let central, central.state == .poweredOn else { return }
        let now = Date()
        // A previous CoreBluetooth scan can survive a long time without a
        // callback. Restart it periodically, retaining ASK authorization.
        if isScanning {
            guard now.timeIntervalSince(bleConnectStarted) >= 15 else { return }
            central.stopScan()
            isScanning = false
            status = "Retrying search for paired Brain..."
        }
        if let current = peripheral {
            if current.state == .connected {
                // CoreBluetooth transport alone is not an encrypted/ready GATT
                // session. Re-discover once, then recreate a stuck connection.
                let elapsed = now.timeIntervalSince(bleConnectStarted)
                if elapsed >= 38 {
                    status = "Bluetooth handshake stalled; reconnecting..."
                    central.cancelPeripheralConnection(current)
                    // Keep reference until didDisconnect (avoids concurrent
                    // duplicate connections to the same peripheral).
                    bleConnectStarted = now
                } else if elapsed >= 16 && bleRecoveryAttempts == 0 {
                    bleRecoveryAttempts = 1
                    status = "Retrying Brain encrypted service discovery..."
                    discoverOrRestoreServices(on: current)
                }
                return
            }
            if current.state == .connecting {
                // IMPORTANT: leave the OS-level pending connection alive.
                // CoreBluetooth can complete it after a long period out of
                // range, including when iOS has suspended the app. A
                // foreground timer must never cancel this background path.
                return
            } else {
                clearConnection()
            }
        }
        guard now.timeIntervalSince(nextBLEAttempt) >= 6 else { return }
        nextBLEAttempt = now
        startConnection()
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
        bleConnectStarted = Date()
        bleRecoveryAttempts = 0
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
        brainBLEReady = false
        bluetoothBrainConnected = false
        commandCharacteristic = nil
        networkCharacteristic = nil
        networkDetailsAvailable = false
        networkRefreshStarted = false
        if !wifiFallbackConnected { pendingCommands.removeAll() }
        waitingForWrite = false
        awaitingBrainAck = false
        brainWriteComplete = false
        brainResponse = nil
        brainReadyReadAttempts = 0
        bleCommandGeneration += 1  // Invalidate any pending ACK timeout.
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
    func sendControlCommand(_ payload: String) {
        if payload == "AI:STOP" { aiLiveStatus = "Stopping" }
        enqueue([payload])
    }
    // Provision directly to the S3 over the authenticated/encrypted BLE relay.
    // Each operation is ACKed before the next one is sent.
    func sendBrainAIPrompt(url: String, model: String, key: String,
                           prompt: String) {
        guard bleReady() else {
            status = "Brain AI configuration requires encrypted Bluetooth"
            return
        }
        guard url.hasPrefix("https://"), !url.contains("@"),
              !model.isEmpty, !key.isEmpty,
              !prompt.isEmpty else {
            status = "AI requires HTTPS URL, model and API key"
            return
        }
        let fields: [(String, String)] = [
            ("U", url), ("M", model), ("K", key),
            ("P", prompt)
        ]
        var commands: [String] = []
        for (name, value) in fields {
            let bytes = Array(value.utf8)
            let maxCount = name == "K" ? 8192 : name == "P" ? 1024 : 256
            guard bytes.count > 0, bytes.count <= maxCount else {
                status = "AI field \(name) is too large"
                return
            }
            commands.append("AI:BEGIN:\(name):\(bytes.count)")
            for offset in stride(from: 0, to: bytes.count, by: 40) {
                let part = bytes[offset..<min(bytes.count, offset + 40)]
                commands.append("AI:DATA:" + part.map {
                    String(format: "%02X", $0)
                }.joined())
            }
            commands.append("AI:END")
        }
        commands.append("AI:GO")
        aiLiveStatus = "Sending prompt"
        enqueue(commands)
        status = "Sending AI prompt to S3 Brain (\(commands.count) commands)"
    }

    // Save the ONE Open WebUI server URL, selected model and revocable API key
    // to S3 NVS over the existing encrypted BLE command channel.
    // No AI:GO here: provisioning must not start a chat or speak.
    func saveBrainAIConnection(url: String, model: String, key: String) {
        guard bleReady() else {
            status = "Open WebUI settings require connected Brain Bluetooth"
            return
        }
        let server = url.trimmingCharacters(in: .whitespacesAndNewlines)
        let modelID = model.trimmingCharacters(in: .whitespacesAndNewlines)
        let secret = key.trimmingCharacters(in: .whitespacesAndNewlines)
        guard server.hasPrefix("https://"), !server.contains("@"),
              !server.contains("#"), !server.contains("?"),
              server.utf8.count <= 256, modelID.utf8.count <= 128,
              !modelID.isEmpty, secret.hasPrefix("sk-"),
              secret.utf8.count <= 8192 else {
            status = "Enter valid HTTPS Open WebUI URL, model and sk- API key"
            return
        }
        let fields = [("U", server), ("M", modelID), ("K", secret)]
        var commands: [String] = []
        for (field, value) in fields {
            let bytes = Array(value.utf8)
            commands.append("AI:BEGIN:\(field):\(bytes.count)")
            for offset in stride(from: 0, to: bytes.count, by: 40) {
                let part = bytes[offset..<min(bytes.count, offset + 40)]
                commands.append("AI:DATA:" + part.map {
                    String(format: "%02X", $0)
                }.joined())
            }
            commands.append("AI:END")
        }
        enqueue(commands)
        status = "Saving one Open WebUI connection to S3 (\(commands.count) BLE commands)"
    }

    // Wi-Fi credentials are provisioned over the connected BLE link.
    // Only use a network that you control. Password is never logged.
    func connectWiFi(ssid: String, password: String) {
        guard bleReady() else {
            status = "Connect to the S3 Brain over Bluetooth to provision Wi-Fi securely"
            return
        }
        let name = ssid.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty && name.utf8.count <= 32,
              password.utf8.count <= 63,
              (password.isEmpty || password.utf8.count >= 8),
              !name.contains("\n"), !password.contains("\n") else {
            status = "Wi-Fi SSID must be 1–32 bytes; password 8–63 bytes (or empty)"
            return
        }
        wifiConnectionState = "CONFIGURING"
        wifiConnectionError = ""
        enqueue(["W:S:\(name)", "W:P:\(password)", "W:C"])
        status = "Sending Wi-Fi configuration to the Brain..."
    }

    func configureIP(dhcp: Bool, ip: String, mask: String, gateway: String, dns: String) {
        guard bleReady() else {
            status = "Connect to the S3 Brain over Bluetooth to change IP settings"
            return
        }
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
        if !bleReady(), wifiFallbackConnected {
            pollLANStatus()
            return
        }
        // Request one field per acknowledged BLE write instead of relying on
        // a burst of notifications from the ESP32.
        enqueue(["W:GET:KEY","W:GET:LINK","W:GET:STATE","W:GET:FAIL",
                 "W:GET:MODE","W:GET:IP","W:GET:MASK",
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
    func disconnectWiFi() { brainWiFiSetting("W:OFF") }
    func enableWiFi() { brainWiFiSetting("W:ON") }
    func forgetWiFi() { brainWiFiSetting("W:FORGET") }
    private func brainWiFiSetting(_ command: String) {
        guard bleReady() else {
            status = "S3 Brain Wi-Fi settings require encrypted Bluetooth"
            return
        }
        enqueue([command])
    }

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
        guard bleReady() || wifiFallbackConnected else {
            status = "Not connected to CuteDisplay"
            return
        }
        guard commands.allSatisfy({ !$0.isEmpty && $0.utf8.count <= 96 }) else {
            status = "Bluetooth command exceeds 96 bytes"
            return
        }
        if !bleReady() && commands.contains(where: { $0.hasPrefix("W:") }) {
            status = "S3 Brain Wi-Fi/IP changes require Bluetooth"
            return
        }
        pendingCommands.append(contentsOf: commands)
        sendNext()
    }

    private func sendNext() {
        guard !waitingForWrite, !pendingCommands.isEmpty else { return }
        if bleReady(), let peripheral, let characteristic = commandCharacteristic {
            // Brain commands require an end-to-end ACK; without the FFF1
            // notification subscription we must NOT flood the UART queue.
            let brainProxy = characteristic.properties.contains(.notify)
            if brainProxy && !characteristic.isNotifying { return }
            let next = pendingCommands.removeFirst()
            guard let data = next.data(using: .utf8) else { return }
            waitingForWrite = true
            awaitingBrainAck = brainProxy
            brainWriteComplete = false
            brainResponse = nil
            bleCommandGeneration += 1
            let thisCommand = bleCommandGeneration
            peripheral.writeValue(data, for: characteristic, type: .withResponse)
            if brainProxy {
                Task { @MainActor [weak self] in
                    try? await Task.sleep(for: .seconds(20))
                    guard let self, self.bleCommandGeneration == thisCommand,
                          self.awaitingBrainAck, self.waitingForWrite else { return }
                    self.awaitingBrainAck = false
                    self.commandCompleted(errorMessage: "Brain UART response timed out (20s)")
                }
            }
        } else if wifiFallbackConnected && lanAuthenticated {
            let next = pendingCommands.removeFirst()
            waitingForWrite = true
            lanConnection?.send(content: Data(("CMD " + next + "\n").utf8),
                                completion: .contentProcessed { [weak self] error in
                if let error {
                    DispatchQueue.main.async { self?.lanFailure(error.localizedDescription) }
                }
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
        bleConnectStarted = Date()
        bleRecoveryAttempts = 0
        found.delegate = self
        status = "Connecting..."
        central.connect(found, options: brainConnectionOptions)
    }

    func centralManager(_ central: CBCentralManager, didConnect device: CBPeripheral) {
        guard device.identifier == authorizedIdentifier() else {
            central.cancelPeripheralConnection(device)
            return
        }
        rememberAuthorized(device.identifier)
        bleConnectStarted = Date()
        bleRecoveryAttempts = 0
        status = "Discovering services..."
        discoverOrRestoreServices(on: device)
    }

    func centralManager(_ central: CBCentralManager,
                        didFailToConnect device: CBPeripheral, error: Error?) {
        clearConnection()
        status = error?.localizedDescription ?? "Connection failed"
        nextBLEAttempt = Date()
        // The foreground timer retries if the saved peripheral reappears.
    }

    func centralManager(_ central: CBCentralManager,
                        didDisconnectPeripheral device: CBPeripheral, error: Error?) {
        // Ignore a late callback from the previous accessory after switching.
        guard peripheral?.identifier == device.identifier else { return }
        clearConnection()
        if !wifiFallbackConnected {
            status = error == nil ? "Brain Bluetooth disconnected" :
                                    "Brain Bluetooth disconnected: \(error!.localizedDescription)"
        }
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
        if characteristic.uuid == commandUUID {
            if let error {
                status = "Brain command notifications unavailable: \(error.localizedDescription)"
                brainBLEReady = false
                bluetoothBrainConnected = false
                isConnected = wifiFallbackConnected
                pendingCommands.removeAll()
                awaitingBrainAck = false
                waitingForWrite = false
            } else {
                sendNext()
            }
            return
        }
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
        if characteristic.uuid == commandUUID {
            if let error {
                brainBLEReady = false
                bluetoothBrainConnected = false
                isConnected = wifiFallbackConnected
                if !wifiFallbackConnected {
                    status = "Bluetooth pairing required: \(error.localizedDescription)"
                }
                return
            }
            if !brainBLEReady {
                // A protected read proves encryption, but NOT that the S3
                // firmware has finished enabling its UART command proxy.
                // Do not flush saved mascot/glyph/Wi-Fi commands until READY.
                let isBrain = characteristic.properties.contains(.notify)
                let response = characteristic.value.flatMap {
                    String(data: $0, encoding: .utf8)
                } ?? ""
                if isBrain && response != "PROXY_READY" {
                    status = response == "PAIRING_FAILED"
                        ? "Brain Bluetooth pairing failed; forget and pair again"
                        : "Waiting for Brain command relay..."
                    brainReadyReadAttempts += 1
                    if brainReadyReadAttempts == 1 || brainReadyReadAttempts.isMultiple(of: 10) {
                        print("[CuteDisplay BLE] FFF1 read attempt \(brainReadyReadAttempts): \(response)")
                    }
                    if brainReadyReadAttempts <= 60 {
                        Task { @MainActor [weak self] in
                            try? await Task.sleep(for: .milliseconds(500))
                            guard let self, !self.isConnected,
                                  let device = self.peripheral,
                                  device.state == .connected,
                                  let control = self.commandCharacteristic else { return }
                            device.readValue(for: control)
                        }
                    } else {
                        status = "Brain FFF1 still not ready (last: \(response)); retrying BLE..."
                    }
                    return
                }
                brainReadyReadAttempts = 0
                if !isBrain {
                    status = "This is not the S3 Brain. Select the Brain in Bluetooth settings."
                    isConnected = wifiFallbackConnected
                    return
                }
                brainBLEReady = true
                bluetoothBrainConnected = true
                isConnected = true
                status = isBrain ? "Connected securely to Brain (Bluetooth)" :
                         "Pair the S3 Brain for network features"
                if wifiFallbackConnected && waitingForWrite {
                    // LAN command completion is indeterminate at handover;
                    // do not duplicate the command via Bluetooth.
                    waitingForWrite = false
                    pendingCommands.removeAll()
                    status = "Bluetooth restored; previous LAN command not replayed"
                }
                stopLANFallback()
                beginBrainDataSubscriptions(on: peripheral)
                // For Brain, sendNext waits until FFF1 notification is active.
                // Legacy C5 FFF1 has no notifications and uses WriteResponse.
                sendNext()
            } else if let data = characteristic.value,
                      let response = String(data: data, encoding: .utf8) {
                if response.hasPrefix("AI:STATUS:") {
                    let state = String(response.dropFirst("AI:STATUS:".count))
                    switch state {
                    case "QUEUED": aiLiveStatus = "Queued"
                    case "CONNECTING": aiLiveStatus = "Connecting to AI server"
                    case "STREAMING": aiLiveStatus = "Kitty is responding"
                    case "COMPLETE": aiLiveStatus = "Complete"
                    case "VOICE_UPLOADING": aiLiveStatus = "Uploading voice"
                    case "TRANSCRIBED": aiLiveStatus = "Voice recognized; asking Kitty"
                    case "VOICE_BUSY": aiLiveStatus = "Failed: Kitty is busy; retry speaking"
                    case "VOICE_ERROR": aiLiveStatus = "Failed: voice recording or transcription error"
                    case "CANCELLED": aiLiveStatus = "Stopped"
                    case "STOPPING": aiLiveStatus = "Stopping"
                    case "WIFI_ERROR": aiLiveStatus = "Failed: S3 Wi-Fi disconnected"
                    case "CONFIG_ERROR": aiLiveStatus = "Failed: check HTTPS URL, model and API key"
                    case "CLOCK_ERROR": aiLiveStatus = "Failed: S3 clock not synchronized"
                    case "NETWORK_ERROR": aiLiveStatus = "Failed: network or TLS connection"
                    case "AUTH_ERROR": aiLiveStatus = "Failed: invalid or unauthorized API key"
                    case "MODEL_OR_URL_ERROR": aiLiveStatus = "Failed: check model ID or endpoint"
                    case "RATE_LIMIT": aiLiveStatus = "Failed: server rate limit"
                    case "SERVER_ERROR": aiLiveStatus = "Failed: AI server returned an error"
                    case "STREAM_INCOMPLETE": aiLiveStatus = "Failed: incomplete AI stream"
                    case "FAILED": if !aiLiveStatus.hasPrefix("Failed:") { aiLiveStatus = "Failed: generation interrupted" }
                    default: aiLiveStatus = "AI: " + state
                    }
                    return
                }
                if awaitingBrainAck && (response.hasPrefix("ACK:") ||
                   response.hasPrefix("ERR:") ||
                   response.hasPrefix("NACK:")) {
                    brainResponse = response
                    finishBrainCommandIfReady()
                }
            }
            return
        }
        if characteristic.uuid == networkCharacteristicUUID {
            guard error == nil, let data = characteristic.value,
                  let value = String(data: data, encoding: .utf8),
                  value.hasPrefix("N:") else { return }
            let fields = value.split(separator: ":", maxSplits: 3,
                                     omittingEmptySubsequences: false).map(String.init)
            guard fields.count >= 2 else { return }
            switch fields[1] {
            case "LINK":
                if fields.count > 2 {
                    wifiConnected = fields[2] == "1"
                    if wifiConnected {
                        wifiConnectionState = "CONNECTED"
                        wifiConnectionError = ""
                    }
                }
            case "STATE":
                if fields.count > 2 {
                    wifiConnectionState = fields[2]
                    if fields[2] == "CONNECTED" {
                        wifiConnected = true
                        wifiConnectionError = ""
                    } else if fields[2] == "OFF" {
                        wifiConnected = false
                    }
                }
            case "FAIL":
                if fields.count > 2 {
                    let reason = fields[2]
                    switch reason {
                    case "0":
                        wifiConnectionError = ""
                    case "201":
                        wifiConnectionError = "Network not found. Check SSID and use 2.4 GHz Wi-Fi."
                    case "202":
                        wifiConnectionError = "Router rejected authentication. Check Wi-Fi password and security."
                    case "15", "204":
                        wifiConnectionError = "Wi-Fi handshake failed. Check password and WPA settings."
                    case "TIMEOUT":
                        wifiConnectionError = "Connection timed out. Check Wi-Fi signal and router settings."
                    case "BEGIN_FAIL":
                        wifiConnectionError = "Brain Wi-Fi could not start. Check the S3 USB Serial Monitor."
                    default:
                        wifiConnectionError = "Wi-Fi disconnect reason: \(reason)"
                    }
                }
            case "MODE":
                if fields.count > 2 { wifiDHCP = fields[2] == "DHCP" }
            case "IP":
                if fields.count > 2 {
                    wifiIP = fields[2]
                    if Self.validIPv4(fields[2]), let id = authorizedIdentifier() {
                        lanIP = fields[2]
                        UserDefaults.standard.set(lanIP, forKey: "cuteBrainIP.\(id.uuidString)")
                    }
                }
            case "KEY":
                if fields.count > 2, fields[2].count == 64,
                   fields[2].allSatisfy({ $0.isHexDigit }),
                   let id = authorizedIdentifier() {
                    saveBrainKey(fields[2], for: id)
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
        if let error, (error as NSError).code == 5 {
            // CBATTError.insufficientAuthentication: preserve any authenticated
            // LAN fallback, but require a new protected BLE read.
            brainBLEReady = false
            bluetoothBrainConnected = false
            isConnected = wifiFallbackConnected
            status = "Brain Bluetooth encryption required; reconnect and pair again"
            if let control = commandCharacteristic { peripheral.readValue(for: control) }
        }
        if let error {
            // The GATT write failed (e.g. pairing not finished).
            awaitingBrainAck = false
            commandCompleted(errorMessage: error.localizedDescription)
        } else if awaitingBrainAck {
            brainWriteComplete = true
            finishBrainCommandIfReady()
        } else {
            // Legacy C5 firmware does not provide FFF1 end-to-end ACKs.
            commandCompleted(errorMessage: nil)
        }
        // Brain: both BLE write callback AND C5 UART ACK must complete.
    }

    private func finishBrainCommandIfReady() {
        guard awaitingBrainAck, brainWriteComplete,
              let response = brainResponse else { return }
        awaitingBrainAck = false
        if response.hasPrefix("ACK:") {
            commandCompleted(errorMessage: nil)
        } else {
            commandCompleted(errorMessage: "Brain rejected command: \(response)")
        }
    }

    private func commandCompleted(errorMessage: String?) {
        waitingForWrite = false
        awaitingBrainAck = false
        brainWriteComplete = false
        brainResponse = nil
        bleCommandGeneration += 1
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
        brainBLEReady && peripheral?.state == .connected && commandCharacteristic != nil
    }

    // The Brain publishes _cutedisplay._tcp via mDNS. Also retain its last
    // authenticated BLE-reported IP as a fallback if discovery is delayed.
    // Every socket is forced onto local Wi-Fi (never cellular).
    private func beginBrainDiscovery() {
        guard lanBrowser == nil else { return }
        let parameters = NWParameters.tcp
        parameters.requiredInterfaceType = .wifi
        let browser = NWBrowser(for: .bonjour(type: "_cutedisplay._tcp", domain: nil),
                                using: parameters)
        browser.browseResultsChangedHandler = { [weak self] results, _ in
            DispatchQueue.main.async {
                self?.brainServiceEndpoint = results.first?.endpoint
            }
        }
        browser.stateUpdateHandler = { [weak self] state in
            if case .failed = state {
                DispatchQueue.main.async {
                    self?.lanBrowser?.cancel()
                    self?.lanBrowser = nil
                }
            }
        }
        lanBrowser = browser
        browser.start(queue: .main)
    }

    private func maintainLAN() {
        // BLE is the primary transport. Never race it with LAN while the
        // paired peripheral is scanning, connecting, or in GATT/security setup.
        // The Brain LAN server deliberately rejects other subnets.
        let bleInProgress = autoReconnect && (isScanning ||
            peripheral?.state == .connecting || peripheral?.state == .connected)
        guard !intentionalDisconnect, !bleReady(), !bleInProgress,
              authorizedIdentifier() != nil, lanToken?.count == 64 else {
            if lanConnection != nil || lanBrowser != nil { stopLANFallback() }
            return
        }
        beginBrainDiscovery()
        if let connection = lanConnection {
            // A TCP connection can remain "ready" after Wi-Fi is lost.
            if lanAuthenticated,
               Date().timeIntervalSince(lanLastReply) > 16 {
                lanFailure("Brain stopped responding over local Wi-Fi")
            }
            return
        }
        guard Date().timeIntervalSince(lanLastAttempt) > 7 else { return }
        let ipEndpoint: NWEndpoint? = Self.validIPv4(lanIP) ?
            .hostPort(host: NWEndpoint.Host(lanIP),
                      port: NWEndpoint.Port(rawValue: 8848)!) : nil
        // Alternate between remembered IP and Bonjour to recover DHCP changes.
        let useBonjour = Int(Date().timeIntervalSince1970 / 7).isMultiple(of: 2)
        guard let endpoint = useBonjour ?
                (brainServiceEndpoint ?? ipEndpoint) :
                (ipEndpoint ?? brainServiceEndpoint) else { return }
        lanLastAttempt = Date()
        let parameters = NWParameters.tcp
        parameters.requiredInterfaceType = .wifi
        let connection = NWConnection(to: endpoint, using: parameters)
        lanConnection = connection
        lanAuthenticated = false
        lanLastReply = Date()
        lanBytes.removeAll()
        connection.stateUpdateHandler = { [weak self, weak connection] state in
            DispatchQueue.main.async {
                guard let self, let connection, self.lanConnection === connection else { return }
                switch state {
                case .ready:
                    self.receiveLAN(connection)
                case .failed(let error):
                    self.lanFailure(error.localizedDescription)
                case .cancelled:
                    self.lanFailure("Connection cancelled")
                default: break
                }
            }
        }
        connection.start(queue: .main)
    }

    private func brainChallengeResponse(_ nonce: String) -> String? {
        guard nonce.count == 32, nonce.allSatisfy({ $0.isHexDigit }),
              let token = lanToken, token.count == 64 else { return nil }
        var bytes: [UInt8] = []
        for offset in stride(from: 0, to: 64, by: 2) {
            let start = token.index(token.startIndex, offsetBy: offset)
            let end = token.index(start, offsetBy: 2)
            guard let byte = UInt8(token[start..<end], radix: 16) else { return nil }
            bytes.append(byte)
        }
        let mac = HMAC<SHA256>.authenticationCode(
            for: Data(nonce.utf8), using: SymmetricKey(data: Data(bytes)))
        return mac.map { String(format: "%02x", $0) }.joined()
    }

    private func receiveLAN(_ connection: NWConnection) {
        connection.receive(minimumIncompleteLength: 1, maximumLength: 1024) {
            [weak self, weak connection] data, _, complete, error in
            DispatchQueue.main.async {
                guard let self, let connection,
                      self.lanConnection === connection else { return }
                if let data { self.lanBytes.append(data) }
                if self.lanBytes.count > 4096 {
                    self.lanFailure("Excessive Brain LAN response")
                    return
                }
                while let newline = self.lanBytes.firstIndex(of: 10) {
                    let line = String(decoding: self.lanBytes.prefix(upTo: newline), as: UTF8.self)
                    self.lanBytes.removeSubrange(...newline)
                    self.handleLANLine(line.trimmingCharacters(in: .whitespacesAndNewlines))
                }
                if complete || error != nil {
                    self.lanFailure(error?.localizedDescription ?? "Connection closed")
                } else {
                    self.receiveLAN(connection)
                }
            }
        }
    }

    private func handleLANLine(_ line: String) {
        lanLastReply = Date()
        if line.hasPrefix("CHALLENGE ") {
            guard let response = brainChallengeResponse(String(line.dropFirst(10))) else {
                lanFailure("Invalid Brain LAN authentication challenge")
                return
            }
            lanConnection?.send(content: Data(("AUTH " + response + "\n").utf8),
                                completion: .contentProcessed { [weak self] error in
                if let error { DispatchQueue.main.async { self?.lanFailure(error.localizedDescription) } }
            })
        } else if line == "OK" {
            lanAuthenticated = true
            wifiFallbackConnected = true
            isConnected = true
            wifiConnected = true
            wifiConnectionState = "CONNECTED"
            networkDetailsAvailable = true
            if Self.validIPv4(lanIP) { wifiIP = lanIP }
            status = "Connected to S3 Brain over local Wi-Fi"
            pollLANStatus()
            sendNext()
        } else if line == "ACK" {
            guard waitingForWrite, wifiFallbackConnected, !bleReady() else { return }
            commandCompleted(errorMessage: nil)
        } else if line.hasPrefix("NACK") || line == "DENIED" {
            if line == "DENIED" {
                lanFailure("Brain rejected LAN authentication; reconnect over BLE")
            } else if waitingForWrite {
                commandCompleted(errorMessage: line == "NACK:BLE_REQUIRED"
                    ? "S3 network configuration requires Bluetooth"
                    : "Brain LAN command rejected: " + line)
            }
        } else if line.hasPrefix("N:") {
            let parts = line.split(separator: ":", maxSplits: 2,
                                   omittingEmptySubsequences: false).map(String.init)
            guard parts.count == 3 else { return }
            switch parts[1] {
            case "LINK": wifiConnected = parts[2] == "1"
            case "STATE": wifiConnectionState = parts[2]
            case "IP":
                wifiIP = parts[2]
                if Self.validIPv4(parts[2]),
                   let id = authorizedIdentifier() {
                    lanIP = parts[2]
                    UserDefaults.standard.set(lanIP, forKey: "cuteBrainIP.\(id.uuidString)")
                }
            case "MODE": wifiDHCP = parts[2] == "DHCP"
            case "MASK": wifiMask = parts[2]
            case "GW": wifiGateway = parts[2]
            case "DNS": wifiDNS = parts[2]
            case "RSSI": wifiRSSI = Int(parts[2]) ?? 0
            default: break
            }
        }
    }

    private func stopLANFallback() {
        lanConnection?.stateUpdateHandler = nil
        lanConnection?.cancel()
        lanConnection = nil
        lanBrowser?.stateUpdateHandler = nil
        lanBrowser?.browseResultsChangedHandler = nil
        lanBrowser?.cancel()
        lanBrowser = nil
        lanAuthenticated = false
        wifiFallbackConnected = false
        lanBytes.removeAll()
    }

    private func lanFailure(_ reason: String) {
        guard lanConnection != nil else { return }
        stopLANFallback()
        if !bleReady() {
            isConnected = false
            if !autoReconnect || (peripheral == nil && !isScanning) {
                status = "Brain Wi-Fi fallback: " + reason
            }
        }
        if waitingForWrite && !bleReady() {
            waitingForWrite = false
            pendingCommands.removeAll()
        }
    }

    private func pollLANStatus() {
        guard wifiFallbackConnected, !bleReady(), lanAuthenticated else { return }
        lanConnection?.send(content: Data("STATUS\n".utf8),
                            completion: .contentProcessed { [weak self] error in
            if let error { DispatchQueue.main.async { self?.lanFailure(error.localizedDescription) } }
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
