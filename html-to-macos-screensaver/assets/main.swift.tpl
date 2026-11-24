import ScreenSaver
import WebKit

final class SaverView: ScreenSaverView {
    private var web: WKWebView?

    override init?(frame: NSRect, isPreview: Bool) {
        super.init(frame: frame, isPreview: isPreview)
        wantsLayer = true
        animationTimeInterval = 1.0 / 60.0

        let config = WKWebViewConfiguration()
        // 屏保的 Web 内容进程常缺少 TZ 环境变量（ICU 回退 GMT），
        // 从宿主进程读正确的系统时区，在文档起始注入页面。
        let tz = TimeZone.current.identifier
            .replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "'", with: "\\'")
        let tzScript = WKUserScript(
            source: "window.__TIMEZONE__='\(tz)';",
            injectionTime: .atDocumentStart, forMainFrameOnly: true)
        config.userContentController.addUserScript(tzScript)
        let w = WKWebView(frame: bounds, configuration: config)
        w.autoresizingMask = [.width, .height]
        addSubview(w)
        web = w

        let bundle = Bundle(for: type(of: self))
        if let resources = bundle.resourceURL,
           let entry = bundle.object(forInfoDictionaryKey: "EntryFile") as? String {
            w.loadFileURL(resources.appendingPathComponent(entry), allowingReadAccessTo: resources)
        }
    }

    required init?(coder: NSCoder) { return nil }
}
