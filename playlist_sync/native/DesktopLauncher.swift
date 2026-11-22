import Cocoa
import WebKit

class PocketSyncLauncher: NSObject, NSApplicationDelegate, WKUIDelegate, WKNavigationDelegate {
    private let window = NSWindow(
        contentRect: NSRect(x: 0, y: 0, width: 1180, height: 800),
        styleMask: [.titled, .closable, .miniaturizable, .resizable],
        backing: .buffered, defer: false
    )
    private var appURL: URL!
    private var loading = true

    func applicationDidFinishLaunching(_ notification: Notification) {
        let project = Bundle.main.object(forInfoDictionaryKey: "PocketSyncProjectPath") as? String
        let packaged = project == nil
        let root = project.map { URL(fileURLWithPath: $0, isDirectory: true) }
            ?? Bundle.main.resourceURL!.appendingPathComponent("project", isDirectory: true)
        let python = packaged
            ? Bundle.main.resourceURL!.appendingPathComponent("python/bin/python3")
            : root.appendingPathComponent(".venv/bin/python")
        let launcher = root.appendingPathComponent("scripts/launch_pocket_sync.py")
        appURL = URL(string: "http://127.0.0.1:\(packaged ? 8879 : 8878)/")!

        NSApplication.shared.applicationIconImage = NSImage(contentsOf: Bundle.main.resourceURL!.appendingPathComponent("PocketSync.icns"))
        window.title = "Pocket Sync"
        window.minSize = NSSize(width: 480, height: 400)
        window.isReleasedWhenClosed = false
        window.center()
        let status = NSTextField(labelWithString: packaged
            ? "Starting Pocket Sync…\nThe first launch may take a few minutes to install audio tools."
            : "Starting Pocket Sync…")
        status.alignment = .center
        status.translatesAutoresizingMaskIntoConstraints = false
        if let content = window.contentView {
            content.addSubview(status)
            NSLayoutConstraint.activate([
                status.centerXAnchor.constraint(equalTo: content.centerXAnchor),
                status.centerYAnchor.constraint(equalTo: content.centerYAnchor),
            ])
        }
        if let value = ProcessInfo.processInfo.environment["POCKET_SYNC_APPEARANCE"] {
            NSApplication.shared.appearance = NSAppearance(named: value == "dark" ? .darkAqua : .aqua)
        }
        window.makeKeyAndOrderFront(nil)
        NSApplication.shared.activate(ignoringOtherApps: true)

        // UI QA uses the real shell against an isolated loopback test server.
        if let testURL = ProcessInfo.processInfo.environment["POCKET_SYNC_TEST_URL"],
           let url = URL(string: testURL), url.scheme == "http", url.host == "127.0.0.1" {
            appURL = url
            showApp()
            return
        }
        guard FileManager.default.isExecutableFile(atPath: python.path),
              FileManager.default.fileExists(atPath: launcher.path) else {
            showError("Pocket Sync could not find its Python environment. Reinstall the app or rerun source setup.")
            return
        }
        DispatchQueue.global(qos: .userInitiated).async {
            let process = Process()
            process.executableURL = python
            process.arguments = ["-B", "-E", "-s", launcher.path] + (packaged ? ["--packaged"] : [])
            process.currentDirectoryURL = root
            let errors = Pipe()
            process.standardError = errors
            process.standardOutput = FileHandle.nullDevice
            do {
                try process.run()
                let detail = String(data: errors.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
                process.waitUntilExit()
                DispatchQueue.main.async {
                    if process.terminationStatus == 0 {
                        self.showApp()
                    } else {
                        self.showError(detail.isEmpty ? "Pocket Sync could not start. Please reopen the app." : detail)
                    }
                }
            } catch {
                DispatchQueue.main.async { self.showError("Pocket Sync could not start: \(error.localizedDescription)") }
            }
        }
    }

    private func showApp() {
        loading = false
        let configuration = WKWebViewConfiguration()
        configuration.mediaTypesRequiringUserActionForPlayback = []
        let webView = WKWebView(frame: window.contentView?.bounds ?? NSRect(x: 0, y: 0, width: 1180, height: 800), configuration: configuration)
        webView.autoresizingMask = [.width, .height]
        webView.uiDelegate = self
        webView.navigationDelegate = self
        window.contentView = webView
        webView.load(URLRequest(url: appURL))
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        if ProcessInfo.processInfo.environment["POCKET_SYNC_TEST_URL"] != nil {
            let message = "Loaded \(webView.url?.absoluteString ?? "unknown") frame=\(webView.frame)\n"
            FileHandle.standardError.write(Data(message.utf8))
        }
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        if (error as NSError).code != NSURLErrorCancelled { showError("Could not load Pocket Sync: " + error.localizedDescription) }
    }

    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        webView.reload()
    }

    private func isLocal(_ url: URL) -> Bool {
        url.scheme == appURL.scheme && url.host == appURL.host && url.port == appURL.port
    }

    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = action.request.url else {
            decisionHandler(.cancel)
            return
        }
        let embeddedYouTube = action.targetFrame?.isMainFrame == false
            && url.scheme == "https"
            && ["www.youtube-nocookie.com", "www.youtube.com"].contains(url.host ?? "")
            && url.path.hasPrefix("/embed/")
        if isLocal(url) || embeddedYouTube {
            decisionHandler(.allow)
        } else {
            if action.navigationType == .linkActivated && ["http", "https"].contains(url.scheme ?? "") {
                NSWorkspace.shared.open(url)
            }
            decisionHandler(.cancel)
        }
    }

    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = action.request.url, ["http", "https"].contains(url.scheme ?? "") {
            if isLocal(url) {
                webView.load(action.request)
            } else {
                NSWorkspace.shared.open(url)
            }
        }
        return nil
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { !loading }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows: Bool) -> Bool {
        if !hasVisibleWindows { window.makeKeyAndOrderFront(nil) }
        return true
    }

    private func showError(_ message: String) {
        let alert = NSAlert()
        alert.messageText = "Couldn’t open Pocket Sync"
        alert.informativeText = message
        alert.alertStyle = .warning
        alert.addButton(withTitle: "OK")
        alert.runModal()
        NSApplication.shared.terminate(nil)
    }
}

let app = NSApplication.shared
let delegate = PocketSyncLauncher()
app.delegate = delegate
app.setActivationPolicy(.regular)
let menu = NSMenu()
let appMenuItem = NSMenuItem()
let appMenu = NSMenu()
appMenu.addItem(withTitle: "Quit Pocket Sync", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
appMenuItem.submenu = appMenu
menu.addItem(appMenuItem)
let editMenuItem = NSMenuItem()
let editMenu = NSMenu(title: "Edit")
editMenu.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
editMenu.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
editMenu.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
editMenu.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
editMenuItem.submenu = editMenu
menu.addItem(editMenuItem)
app.mainMenu = menu
app.run()
