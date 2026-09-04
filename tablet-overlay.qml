import QtQuick
import QtQuick.Window
import org.kde.layershell 1.0 as LayerShell

Window {
    id: root
    visible: true
    color: "transparent"
    flags: Qt.FramelessWindowHint | Qt.WindowTransparentForInput | Qt.WindowStaysOnTopHint

    LayerShell.Window.layer: LayerShell.Window.LayerOverlay
    LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorBottom
                             | LayerShell.Window.AnchorLeft | LayerShell.Window.AnchorRight
    LayerShell.Window.exclusionZone: -1
    LayerShell.Window.keyboardInteractivity: LayerShell.Window.KeyboardInteractivityNone

    readonly property color dim: Qt.rgba(0, 0, 0, dimval)

    Rectangle { x: 0;       y: 0;       width: root.width;           height: py;                    color: root.dim }
    Rectangle { x: 0;       y: py + ph; width: root.width;           height: root.height - py - ph; color: root.dim }
    Rectangle { x: 0;       y: py;      width: px;                   height: ph;                    color: root.dim }
    Rectangle { x: px + pw; y: py;      width: root.width - px - pw; height: ph;                    color: root.dim }

    // border drawn INSIDE the clear rectangle - never crosses the screen edge
    Rectangle {
        x: px; y: py; width: pw; height: ph
        color: "transparent"
        border.color: "#e6a817"
        border.width: 2
    }
}
