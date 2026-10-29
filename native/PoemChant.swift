import AppKit
import WebKit
import UniformTypeIdentifiers

final class StudioApplication: NSObject, NSApplicationDelegate, NSWindowDelegate, WKNavigationDelegate, WKUIDelegate, WKDownloadDelegate {
    var window: NSWindow!
    var webView: WKWebView!
    var backend: Process?
    var startupTimer: Timer?
    var startedAt = Date()
    var readyURL: URL!
    var temporaryFolder: URL!
    var baseURL: URL?
    var allowClose = false
    var logHandle: FileHandle?

    func applicationDidFinishLaunching(_ notification: Notification) {
        buildMenus()
        let screen = NSScreen.main?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1440, height: 900)
        let size = NSSize(width: min(1300, screen.width - 36), height: min(900, screen.height - 36))
        window = NSWindow(contentRect: NSRect(origin: .zero, size: size), styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "吟谱 · PoemChant Studio"
        window.minSize = NSSize(width: 760, height: 600)
        window.delegate = self
        window.isReleasedWhenClosed = false
        window.setFrameAutosaveName("PoemChantStudioMain")
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()
        webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = self
        webView.uiDelegate = self
        webView.allowsBackForwardNavigationGestures = false
        window.contentView = webView
        let loading = "<html lang='zh-CN'><meta charset='utf-8'><body style='background:#f7f5ef;color:#286b5e;font:20px -apple-system;text-align:center;padding-top:180px'>吟谱<br><p style='font-size:14px'>正在启动本地谱面工作室…</p></body></html>"
        webView.loadHTMLString(loading, baseURL: nil)
        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        startBackend()
    }

    func buildMenus() {
        let menu = NSMenu()
        let appMenuItem = NSMenuItem()
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "关于吟谱", action: #selector(showAbout), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "隐藏吟谱", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "退出吟谱", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appMenuItem.submenu = appMenu
        menu.addItem(appMenuItem)
        let editItem = NSMenuItem()
        let editMenu = NSMenu(title: "编辑")
        for (title, action, key) in [("撤销", "undo:", "z"), ("剪切", "cut:", "x"), ("复制", "copy:", "c"), ("粘贴", "paste:", "v"), ("全选", "selectAll:", "a")] {
            editMenu.addItem(withTitle: title, action: Selector(action), keyEquivalent: key)
        }
        editItem.submenu = editMenu
        menu.addItem(editItem)
        let windowItem = NSMenuItem()
        let windowMenu = NSMenu(title: "窗口")
        windowMenu.addItem(withTitle: "最小化", action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m")
        windowItem.submenu = windowMenu
        menu.addItem(windowItem)
        NSApp.mainMenu = menu
        NSApp.windowsMenu = windowMenu
    }

    @objc func showAbout() {
        webView.evaluateJavaScript("document.getElementById('about')?.showModal()", completionHandler: nil)
    }

    func showError(_ message: String) {
        let alert = NSAlert()
        alert.messageText = "吟谱未能完成操作"
        alert.informativeText = message
        alert.alertStyle = .warning
        alert.addButton(withTitle: "知道了")
        alert.runModal()
    }

    func startBackend() {
        do {
            temporaryFolder = FileManager.default.temporaryDirectory.appendingPathComponent("PoemChant-" + UUID().uuidString, isDirectory: true)
            try FileManager.default.createDirectory(at: temporaryFolder, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
            readyURL = temporaryFolder.appendingPathComponent("ready.json")
            let support = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0].appendingPathComponent("PoemChant Studio", isDirectory: true)
            try FileManager.default.createDirectory(at: support, withIntermediateDirectories: true)
            let logURL = support.appendingPathComponent("application.log")
            FileManager.default.createFile(atPath: logURL.path, contents: nil)
            logHandle = try FileHandle(forWritingTo: logURL)
            let helper = Bundle.main.resourceURL!.appendingPathComponent("backend/PoemChantBackend")
            let process = Process()
            process.executableURL = helper
            process.arguments = ["serve", "--no-browser", "--port", "0", "--ready-file", readyURL.path]
            process.currentDirectoryURL = support
            var environment = ProcessInfo.processInfo.environment
            for key in ["OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"] { environment[key] = "1" }
            environment["PYTHONUTF8"] = "1"
            process.environment = environment
            process.standardOutput = logHandle
            process.standardError = logHandle
            try process.run()
            backend = process
            startedAt = Date()
            startupTimer = Timer.scheduledTimer(withTimeInterval: 0.15, repeats: true) { [weak self] _ in self?.pollReady() }
        } catch {
            showError("本地服务启动失败：\(error.localizedDescription)")
        }
    }

    func pollReady() {
        if let data = try? Data(contentsOf: readyURL),
           let info = try? JSONSerialization.jsonObject(with: data) as? [String: String],
           let string = info["url"], let url = URL(string: string), url.host == "127.0.0.1" {
            startupTimer?.invalidate()
            baseURL = url
            webView.load(URLRequest(url: url))
            return
        }
        if backend?.isRunning != true || Date().timeIntervalSince(startedAt) > 40 {
            startupTimer?.invalidate()
            showError("本地服务未就绪。请查看应用数据目录中的 application.log，或使用开源版构建说明重新构建。")
        }
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = navigationAction.request.url else { decisionHandler(.cancel); return }
        if url.scheme == "about" { decisionHandler(.allow); return }
        guard url.host == baseURL?.host, url.port == baseURL?.port, url.scheme == "http" else {
            decisionHandler(.cancel)
            return
        }
        if navigationAction.shouldPerformDownload || URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems?.contains(where: { $0.name == "download" && $0.value == "1" }) == true {
            decisionHandler(.download)
        } else { decisionHandler(.allow) }
    }

    func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) { download.delegate = self }
    func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) { download.delegate = self }

    func download(_ download: WKDownload, decideDestinationUsing response: URLResponse, suggestedFilename: String, completionHandler: @escaping (URL?) -> Void) {
        let panel = NSSavePanel()
        panel.nameFieldStringValue = suggestedFilename
        panel.canCreateDirectories = true
        panel.beginSheetModal(for: window) { result in completionHandler(result == .OK ? panel.url : nil) }
    }

    func download(_ download: WKDownload, didFailWithError error: Error, resumeData: Data?) {
        if (error as NSError).code != NSURLErrorCancelled { showError("导出失败：" + error.localizedDescription) }
    }

    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping ([URL]?) -> Void) {
        let panel = NSOpenPanel()
        panel.canChooseFiles = true
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = false
        panel.allowedContentTypes = [.json, .zip]
        panel.beginSheetModal(for: window) { response in completionHandler(response == .OK ? panel.urls : nil) }
    }

    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        let alert = NSAlert()
        alert.messageText = "确认操作"
        alert.informativeText = message
        alert.addButton(withTitle: "继续")
        alert.addButton(withTitle: "取消")
        alert.beginSheetModal(for: window) { result in completionHandler(result == .alertFirstButtonReturn) }
    }

    func confirmDiscard(_ completion: @escaping (Bool) -> Void) {
        webView.evaluateJavaScript("window.poemchantHasUnsavedChanges ? window.poemchantHasUnsavedChanges() : false") { [weak self] result, _ in
            guard let self else { completion(true); return }
            guard (result as? Bool) == true else { completion(true); return }
            let alert = NSAlert()
            alert.messageText = "还有未保存的修改"
            alert.informativeText = "退出将放弃尚未保存的编辑，已保存的各稿不受影响。"
            alert.addButton(withTitle: "继续编辑")
            alert.addButton(withTitle: "放弃修改并退出")
            alert.beginSheetModal(for: self.window) { response in completion(response == .alertSecondButtonReturn) }
        }
    }

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        if allowClose { return true }
        confirmDiscard { [weak self] shouldClose in
            if shouldClose { self?.allowClose = true; self?.window.close() }
        }
        return false
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if allowClose { return .terminateNow }
        confirmDiscard { shouldClose in NSApp.reply(toApplicationShouldTerminate: shouldClose) }
        return .terminateLater
    }

    func applicationWillTerminate(_ notification: Notification) {
        startupTimer?.invalidate()
        backend?.terminate()
        try? logHandle?.close()
        if let temporaryFolder { try? FileManager.default.removeItem(at: temporaryFolder) }
    }
}

let app = NSApplication.shared
let delegate = StudioApplication()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
