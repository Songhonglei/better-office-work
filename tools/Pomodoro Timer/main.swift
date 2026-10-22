import Cocoa
import WebKit

let app = NSApplication.shared
app.setActivationPolicy(.regular)

let window = NSWindow(
    contentRect: NSRect(x: 0, y: 0, width: 400, height: 640),
    styleMask: [.titled, .closable, .miniaturizable, .resizable],
    backing: .buffered,
    defer: false
)
window.title = "番茄钟"
window.titlebarAppearsTransparent = true
window.titleVisibility = .hidden
window.isMovableByWindowBackground = true
window.backgroundColor = NSColor(srgbRed: 0.024, green: 0.031, blue: 0.063, alpha: 1)
window.minSize = NSSize(width: 320, height: 540)
window.center()

let config = WKWebViewConfiguration()
let webView = WKWebView(frame: window.contentView!.bounds, configuration: config)
webView.autoresizingMask = [.width, .height]
if let url = Bundle.main.url(forResource: "index", withExtension: "html") {
    webView.loadFileURL(url, allowingReadAccessTo: url.deletingLastPathComponent())
}
window.contentView!.addSubview(webView)

window.makeKeyAndOrderFront(nil)
app.activate(ignoringOtherApps: true)
app.run()
