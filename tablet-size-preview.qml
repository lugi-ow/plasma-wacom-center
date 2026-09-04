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

    property int pw: 100
    property int ph: 66
    property int pct: 71
    property bool shown: true

    Item {
        anchors.fill: parent
        opacity: root.shown ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 450 } }

        Rectangle {
            anchors.centerIn: parent
            width: root.pw; height: root.ph
            color: Qt.rgba(0.9, 0.66, 0.09, 0.10)
            border.color: "#e6a817"
            border.width: 3
            Behavior on width  { NumberAnimation { duration: 90 } }
            Behavior on height { NumberAnimation { duration: 90 } }
        }
        Text {
            anchors.centerIn: parent
            text: root.pct + "%"
            color: "white"
            style: Text.Outline
            styleColor: "black"
            font.pixelSize: 64
            font.bold: true
        }
    }
}
