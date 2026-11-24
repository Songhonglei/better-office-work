import Foundation
import ScreenSaver

guard CommandLine.arguments.count == 2,
      let bundle = Bundle(path: CommandLine.arguments[1]),
      bundle.load(),
      let viewClass = bundle.principalClass as? ScreenSaverView.Type,
      let view = viewClass.init(frame: NSRect(x: 0, y: 0, width: 800, height: 600), isPreview: true) else {
    print("屏保加载自检失败")
    exit(1)
}
withExtendedLifetime(view) { print("屏保加载自检通过") }
