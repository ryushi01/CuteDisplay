import Foundation
import CoreBluetooth
import Combine
import UIKit

final class BluetoothManager: NSObject, ObservableObject {
    @Published var isConnected = false
    @Published var isScanning = false
    @Published var status = "Starting Bluetooth..."
    @Published var brightness = 75
    @Published var batteryLevel: Int? = nil
    @Published var isSendingDrinks = false

    private var central: CBCentralManager!
    private var peripheral: CBPeripheral?
    private var commandCharacteristic: CBCharacteristic?
    private let controlServiceUUID = CBUUID(string: "FFF0")
    private let commandUUID = CBUUID(string: "FFF1")
    private let batteryServiceUUID = CBUUID(string: "180F")
    private let batteryLevelUUID = CBUUID(string: "2A19")

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
        central = CBCentralManager(delegate: self, queue: nil)
    }

    func connect() {
        if isSimulator { status = "Simulator / Demo Mode"; return }
        guard central.state == .poweredOn else { status = "Bluetooth is not ready"; return }
        if peripheral != nil { disconnect(); return }
        batteryLevel = nil
        isScanning = true
        status = "Searching for CuteDisplay..."
        central.scanForPeripherals(withServices: [controlServiceUUID], options: nil)
    }

    func disconnect() {
        if isScanning { central.stopScan(); isScanning = false }
        if let peripheral {
            central.cancelPeripheralConnection(peripheral)
        } else {
            clearConnection()
            status = "Disconnected"
        }
    }

    private func clearConnection() {
        isConnected = false
        isScanning = false
        batteryLevel = nil
        commandCharacteristic = nil
        pendingCommands.removeAll()
        waitingForWrite = false
        uploadsRemaining = 0
        deferredDrinks = nil
        isSendingDrinks = false
        peripheral = nil
    }

    // Queue 16x16 Japanese glyphs before the UTF-8 text that refers to them.
    func sendMessage(_ text: String) {
        let data = Array(text.utf8)
        guard data.count <= 96 else { status = "Message exceeds 96 UTF-8 bytes"; return }
        enqueue(glyphPackets(for: [text]) + [text])
    }
    func sendDrinksPayload(_ payload: String) { enqueue([payload]) }

    func setTheme(_ index: Int) {
        enqueue(["T:\(min(24,max(0,index)))"])
    }

    private func glyphPackets(for strings: [String]) -> [String] {
        let scalars = Set(strings.joined().unicodeScalars.filter { $0.value > 127 })
        return scalars.sorted { $0.value < $1.value }.compactMap { scalar in
            guard let bitmap = Self.bitmap(for: scalar) else { return nil }
            let hex = bitmap.map { String(format: "%02X", $0) }.joined()
            return "G:\(String(scalar.value, radix: 16).uppercased()):\(hex)"
        }
    }

    // Rasterize each Japanese character with the iPhone's installed system fonts.
    // One foreground bit for each pixel, row-major, 16x16 = 32 bytes.
    private static func bitmap(for scalar: Unicode.Scalar) -> [UInt8]? {
        let side = 16
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
            let string = String(scalar) as NSString
            let font = UIFont.systemFont(ofSize: 15, weight: .bold)
            let attributes: [NSAttributedString.Key: Any] = [
                .font: font,
                .foregroundColor: UIColor.white
            ]
            string.draw(in: CGRect(x: 0, y: -2, width: 16, height: 19),
                        withAttributes: attributes)
            return true
        }
        guard ok else { return nil }
        var data = [UInt8](repeating: 0, count: 32)
        for y in 0..<16 {
            for x in 0..<16 {
                // UIKit text drawing into a raw CoreGraphics bitmap has a
                // bottom-up row orientation. Flip the sampled rows so
                // row zero sent to the ESP32 is the top of the glyph.
                let off = ((15 - y) * 16 + x) * 4
                let lit = Int(rgb[off]) + Int(rgb[off+1]) + Int(rgb[off+2]) > 330
                if lit { data[y*2 + x/8] |= UInt8(0x80 >> (x%8)) }
            }
        }
        return data
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
    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        if isSimulator { status = "Simulator / Demo Mode"; return }
        switch central.state {
        case .poweredOn: status = "Ready to connect"
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
        central.stopScan()
        isScanning = false
        peripheral = found
        found.delegate = self
        status = "Connecting..."
        central.connect(found, options: nil)
    }

    func centralManager(_ central: CBCentralManager, didConnect device: CBPeripheral) {
        status = "Discovering services..."
        device.discoverServices([controlServiceUUID, batteryServiceUUID])
    }

    func centralManager(_ central: CBCentralManager,
                        didFailToConnect device: CBPeripheral, error: Error?) {
        clearConnection()
        status = error?.localizedDescription ?? "Connection failed"
    }

    func centralManager(_ central: CBCentralManager,
                        didDisconnectPeripheral device: CBPeripheral, error: Error?) {
        clearConnection()
        status = error == nil ? "Disconnected" : "Disconnected: \(error!.localizedDescription)"
    }
}

extension BluetoothManager: CBPeripheralDelegate {
    func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
        if let error { status = "Service error: \(error.localizedDescription)"; return }
        guard let services = peripheral.services else { return }
        for service in services {
            if service.uuid == controlServiceUUID {
                peripheral.discoverCharacteristics([commandUUID], for: service)
            } else if service.uuid == batteryServiceUUID {
                peripheral.discoverCharacteristics([batteryLevelUUID], for: service)
            }
        }
    }

    func peripheral(_ peripheral: CBPeripheral,
                    didDiscoverCharacteristicsFor service: CBService, error: Error?) {
        if let error { status = "Characteristic error: \(error.localizedDescription)"; return }
        for characteristic in service.characteristics ?? [] {
            if service.uuid == controlServiceUUID && characteristic.uuid == commandUUID {
                commandCharacteristic = characteristic
                isConnected = true
                status = "Connected to CuteDisplay"
            } else if service.uuid == batteryServiceUUID && characteristic.uuid == batteryLevelUUID {
                if characteristic.properties.contains(.read) {
                    peripheral.readValue(for: characteristic)
                }
                if characteristic.properties.contains(.notify) {
                    peripheral.setNotifyValue(true, for: characteristic)
                }
            }
        }
    }

    func peripheral(_ peripheral: CBPeripheral,
                    didUpdateValueFor characteristic: CBCharacteristic, error: Error?) {
        guard characteristic.uuid == batteryLevelUUID else { return }
        if error != nil { batteryLevel = nil; return }
        if let data = characteristic.value, data.count == 1,
           let level = data.first, level <= 100 {
            batteryLevel = Int(level)
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