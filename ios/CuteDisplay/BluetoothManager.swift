import Foundation
import CoreBluetooth
import AccessorySetupKit
import Combine
import UIKit
import UserNotifications

final class BluetoothManager: NSObject, ObservableObject {
    @Published var isConnected = false
    @Published var isScanning = false
    @Published var status = "Starting Bluetooth..."
    @Published var brightness = 75
    @Published var batteryLevel: Int? = nil
    @Published var batteryVoltage: Double?
    @Published var wifiConnected = false
    @Published var batteryCurrent: Double?
    @Published var batteryTemperature: Int?
    @Published var batteryHealth: Int?
    @Published var minutesToEmpty: Int?
    @Published var minutesToFull: Int?
    @Published var lastPowerUpdate: Date?
    @Published var autoReconnect = UserDefaults.standard.object(forKey: "cuteAutoReconnect") as? Bool ?? true
    @Published var rememberedDeviceID = UserDefaults.standard.string(forKey: "cutePeripheralID")
    @Published var isSendingDrinks = false
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
    private var intentionalDisconnect = false
    private var restoredPeripherals: [CBPeripheral] = []

    // One write at a time. Particularly important for D:RESET / D:ADD / D:SHOW.
    private var pendingCommands: [String] = []
    private var waitingForWrite = false
    private var uploadsRemaining = 0
    // Latest-wins drink updates: don't discard edits during a BLE upload.
    private var deferredDrinks: [(name: String, count: Int)]? = nil

    var isSimulator: Bool {
        #if targetEnvironment(simulator)
        true
        #else
        false
        #endif
    }

    override init() {
        super.init()
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

    // AccessorySetupKit is the authoritative accessory authorization store.
    private func authorizedIdentifier() -> UUID? {
        accessorySession.accessories.first(where: { $0.bluetoothIdentifier != nil })?.bluetoothIdentifier
    }
    private func handleAccessoryEvent(_ event: ASAccessoryEvent) {
        switch event.eventType {
        case .activated:
            accessorySessionReady = true
            if authorizedIdentifier() == nil { clearRememberedDevice() }
            if let id = authorizedIdentifier() {
                rememberAuthorized(id)
                ensureBluetoothManager()
                recoverRestoredPeripheralIfPossible()
                if autoReconnect { startConnection() }
            }
        case .accessoryAdded, .accessoryChanged:
            pendingAccessory = event.accessory
            if event.eventType == .accessoryChanged, let id = authorizedIdentifier() {
                rememberAuthorized(id)
                ensureBluetoothManager()
                recoverRestoredPeripheralIfPossible()
                if autoReconnect { startConnection() }
            }
        case .pickerDidDismiss:
            if let id = pendingAccessory?.bluetoothIdentifier {
                rememberAuthorized(id)
                intentionalDisconnect = false
                ensureBluetoothManager()
                recoverRestoredPeripheralIfPossible()
                startConnection()
            }
            pendingAccessory = nil
        case .accessoryRemoved:
            guard authorizedIdentifier() == nil else { return }
            clearRememberedDevice()
            intentionalDisconnect = true
            if let peripheral { central?.cancelPeripheralConnection(peripheral) }
            clearConnection()
            status = "Accessory removed in iOS settings"
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
        if let services = device.services, !services.isEmpty {
            inspectServices(on: device, services: services)
        } else {
            device.discoverServices([controlServiceUUID, batteryServiceUUID, powerServiceUUID])
        }
    }

    private func inspectServices(on device: CBPeripheral, services: [CBService]) {
        for service in services {
            let uuids: [CBUUID]
            switch service.uuid {
            case controlServiceUUID: uuids = [commandUUID]
            case batteryServiceUUID: uuids = [batteryLevelUUID]
            case powerServiceUUID: uuids = [powerCharacteristicUUID]
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
                sendNext()
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
        var descriptor = ASDiscoveryDescriptor()
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
        if !enabled && isScanning { central?.stopScan(); isScanning = false }
    }
    // Remove authorization through the system UI, not by only deleting UserDefaults.
    func forgetDevice() {
        guard let accessory = accessorySession.accessories.first(where: { $0.bluetoothIdentifier != nil }) else {
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
        if let peripheral { central?.cancelPeripheralConnection(peripheral) }
        else { clearConnection(); status = "Disconnected" }
    }

    private func clearConnection() {
        isConnected = false
        isScanning = false
        batteryLevel = nil
        batteryVoltage = nil
        batteryCurrent = nil
        batteryTemperature = nil
        batteryHealth = nil
        minutesToEmpty = nil
        minutesToFull = nil
        lastPowerUpdate = nil
        commandCharacteristic = nil
        pendingCommands.removeAll()
        waitingForWrite = false
        uploadsRemaining = 0
        deferredDrinks = nil
        isSendingDrinks = false
        peripheral = nil
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
    func sendDrinksPayload(_ payload: String) { enqueue([payload]) }

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
        guard !isSimulator, isConnected, !isSendingDrinks else { return }
        enqueue(["P:OFF"])
        status = "Power-off requested — press board RESET to wake"
    }

    func setBrightness(_ value: Int) {
        brightness = min(100, max(0, value))
        enqueue(["B:\(brightness)"])
    }

    // One complete snapshot at a time. When another edit arrives during an upload,
    // retain only the newest snapshot and send it immediately after completion.
    func sendDrinks(_ items: [(name: String, count: Int)]) {
        let limited = Array(items.prefix(24))
        guard limited.allSatisfy({ !$0.name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }) else {
            status = "Drink names cannot be empty"
            return
        }
        guard limited.allSatisfy({ "D:ADD:\(String($0.name.prefix(12))),\(min(9999, max(0, $0.count)))".utf8.count <= 96 }) else {
            status = "A drink name exceeds the BLE limit"
            return
        }
        if isSimulator { status = "Demo Mode — preview updated"; return }
        guard isConnected else { return }
        if isSendingDrinks {
            deferredDrinks = limited
            status = "Another edit queued for syncing..."
            return
        }
        startDrinkUpload(limited)
    }

    private func startDrinkUpload(_ items: [(name: String, count: Int)]) {
        let entries = items.map { item in
            "D:ADD:\(String(item.name.prefix(12))),\(min(9999, max(0, item.count)))"
        }
        let batch = glyphPackets(for: items.map(\.name)) + ["D:RESET"] + entries + ["D:SHOW"]
        guard batch.allSatisfy({ $0.utf8.count <= 96 }) else {
            status = "Bluetooth payload too long"
            return
        }
        // Previous UI commands can be in the queue. All commands in this batch
        // are appended after them, so upload progress is tracked with a sentinel
        // count that includes those earlier queued commands.
        uploadsRemaining = batch.count + pendingCommands.count + (waitingForWrite ? 1 : 0)
        isSendingDrinks = true
        status = "Synchronizing \(items.count) drinks..."
        enqueue(batch)
    }

    // Reapply settings after reconnect, then show the requested mode.
    // Commands are queued in order and use Write With Response.
    func restoreState(theme: Int, character: Int, mood: Int,
                      visible: Bool, size: Int, font: Int,
                      bubble: Bool, typewriter: Bool, brightness: Int,
                      modeIsDrinks: Bool, message: String,
                      drinks: [(name: String, count: Int)]) {
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
        // Restore the complete drink list even if Message Mode is selected.
        // In Message Mode the final queued command returns the LCD to the message.
        sendDrinks(drinks)
        if !modeIsDrinks { sendMessage(message) }
    }

    private func enqueue(_ commands: [String]) {
        if isSimulator { status = "Demo Mode — no Bluetooth sent"; return }
        guard isConnected, peripheral != nil, commandCharacteristic != nil else {
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
        guard !waitingForWrite,
              !pendingCommands.isEmpty,
              let peripheral,
              let characteristic = commandCharacteristic else { return }
        let next = pendingCommands.removeFirst()
        guard let data = next.data(using: .utf8) else { return }
        waitingForWrite = true
        peripheral.writeValue(data, for: characteristic, type: .withResponse)
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
                    didUpdateValueFor characteristic: CBCharacteristic, error: Error?) {
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
        waitingForWrite = false
        if let error {
            pendingCommands.removeAll()
            uploadsRemaining = 0
            isSendingDrinks = false
            status = "Send failed: \(error.localizedDescription)"
            return
        }
        if uploadsRemaining > 0 {
            uploadsRemaining -= 1
            if uploadsRemaining == 0 {
                isSendingDrinks = false
                status = "Drink list synchronized"
                if let latest = deferredDrinks {
                    deferredDrinks = nil
                    startDrinkUpload(latest)
                }
            }
        }
        sendNext()
    }
}
extension BluetoothManager: UNUserNotificationCenterDelegate {
    func userNotificationCenter(_ center: UNUserNotificationCenter,
                                willPresent notification: UNNotification,
                                withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([.banner, .list, .sound])
    }
}
