import Cocoa

let app = NSApplication.shared
app.setActivationPolicy(.regular)
app.finishLaunching()
let panel = NSOpenPanel()
panel.title = "Pocket Sync — Choose Folder"
panel.message = "Select a music folder on your Mac or a connected MP3 player."
panel.prompt = "Choose folder"
panel.canChooseFiles = false
panel.canChooseDirectories = true
panel.allowsMultipleSelection = false
panel.canCreateDirectories = true
panel.resolvesAliases = true
if CommandLine.arguments.count > 1 {
    panel.directoryURL = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
}
app.activate(ignoringOtherApps: true)
panel.makeKeyAndOrderFront(nil)
let response = panel.runModal()
let path: Any = response == .OK ? (panel.url?.path as Any? ?? NSNull()) : NSNull()
let data = try JSONSerialization.data(withJSONObject: ["path": path])
FileHandle.standardOutput.write(data)
FileHandle.standardOutput.write(Data([10]))
