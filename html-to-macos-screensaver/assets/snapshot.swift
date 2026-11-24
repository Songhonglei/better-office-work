import Cocoa
import WebKit

// snapshot.swift — 离屏渲染 HTML 并截图为 PNG
// 用法: snapshot <html文件> <输出.png> <宽> <高> [渲染等待秒数] [文档起始注入的JS]
let args = CommandLine.arguments
guard args.count >= 5 else {
    print("usage: snapshot <html> <out.png> <w> <h> [delay] [injectJS]"); exit(1)
}
let url = URL(fileURLWithPath: args[1])
let out = URL(fileURLWithPath: args[2])
let w = Int(args[3]) ?? 5120
let h = Int(args[4]) ?? 2880
let delay = Double(args.count > 5 ? args[5] : "3") ?? 3
let injectJS = args.count > 6 ? args[6] : nil

let app = NSApplication.shared
app.setActivationPolicy(.accessory)

let config = WKWebViewConfiguration()
if let js = injectJS {
    let script = WKUserScript(source: js, injectionTime: .atDocumentStart, forMainFrameOnly: true)
    config.userContentController.addUserScript(script)
}
let web = WKWebView(frame: NSRect(x: 0, y: 0, width: w, height: h), configuration: config)
web.loadFileURL(url, allowingReadAccessTo: url.deletingLastPathComponent())

// 看门狗：页面崩溃或回调丢失时避免永久挂起
DispatchQueue.main.asyncAfter(deadline: .now() + delay + 20) {
    print("watchdog timeout"); exit(2)
}

DispatchQueue.main.asyncAfter(deadline: .now() + delay) {
    // 离屏快照不渲染 SVG 滤镜（如 feTurbulence/feDisplacementMap），
    // 会导致被滤镜作用的元素整块缺失——截图前统一禁用，保证内容完整
    web.evaluateJavaScript("""
      document.querySelectorAll('*').forEach(e => {
        if (getComputedStyle(e).filter.includes('url(')) e.style.filter = 'none';
      }); 'ok';
    """) { _, _ in
        let cfg = WKSnapshotConfiguration()
        cfg.rect = NSRect(x: 0, y: 0, width: w, height: h)
        web.takeSnapshot(with: cfg) { img, err in
            defer { app.terminate(nil) }
            guard let img, err == nil,
                  let tiff = img.tiffRepresentation,
                  let rep = NSBitmapImageRep(data: tiff),
                  let png = rep.representation(using: .png, properties: [:])
            else { print("snapshot failed:", err?.localizedDescription ?? "nil image"); exit(1) }
            do { try png.write(to: out); print("saved:", out.path) }
            catch { print("write failed:", error.localizedDescription); exit(1) }
        }
    }
}
app.run()
