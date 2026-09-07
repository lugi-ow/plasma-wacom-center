import QtQuick
import QtQuick.Window
import QtQuick.Shapes
import org.kde.layershell 1.0 as LayerShell

// The one drawing behind every overlay of the toolkit: precision mode itself,
// the preview ghost (a finger resting on the precision key), the size preview
// (a ring tick outside the mode) and the PrM ghost (the area being dragged).
// Dim bands around a clear rectangle and a 2 px amber border drawn INSIDE
// it, so it never crosses the screen edge. `waiting` turns the border into
// short dashes that flow clockwise: this rectangle is a preview, waiting to
// be activated. `shown` false fades everything out (the size preview fades
// before it quits). The loaders (tablet-overlay.py, tablet-size-preview.py)
// set the properties from Python with root.setProperty; nothing is read from
// a context.

// ── chunk: overlay-window
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

    property int px: 0             // the clear rectangle, in pixels
    property int py: 0
    property int pw: 100
    property int ph: 66
    property real dimval: 0.35     // alpha of the bands outside it
    property bool waiting: false   // true: dashed border flowing clockwise (a preview)
    property bool shown: true      // false: fade out over 450 ms
    property real phase: 0         // dash offset in pen widths; the animation drives it while waiting

    readonly property color dim: Qt.rgba(0, 0, 0, dimval)
    readonly property color amber: "#e6a817"

    // ── chunk: fading-item
    Item {
        anchors.fill: parent
        opacity: root.shown ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 450 } }

        // ── chunk: dim-bands
        Rectangle { x: 0;                 y: 0;                 width: root.width;                     height: root.py;                          color: root.dim }
        Rectangle { x: 0;                 y: root.py + root.ph; width: root.width;                     height: root.height - root.py - root.ph;  color: root.dim }
        Rectangle { x: 0;                 y: root.py;           width: root.px;                        height: root.ph;                          color: root.dim }
        Rectangle { x: root.px + root.pw; y: root.py;           width: root.width - root.px - root.pw; height: root.ph;                          color: root.dim }

        // ── chunk: solid-border
        Rectangle {   // precision mode: the mapping is live
            x: root.px; y: root.py; width: root.pw; height: root.ph
            visible: !root.waiting
            color: "transparent"
            border.color: root.amber
            border.width: 2
        }

        // ── chunk: waiting-border
        Shape {       // a preview: the same border as dashes, flowing clockwise
            x: root.px; y: root.py; width: root.pw; height: root.ph
            visible: root.waiting
            ShapePath {
                strokeColor: root.amber
                strokeWidth: 2
                fillColor: "transparent"
                strokeStyle: ShapePath.DashLine
                dashPattern: [2.5, 2.5]        // in pen widths: 5 px dash, 5 px gap
                dashOffset: root.phase
                capStyle: ShapePath.FlatCap
                joinStyle: ShapePath.MiterJoin
                startX: 1; startY: 1           // the stroke is centred on the path: 1 px in keeps it inside
                PathLine { x: root.pw - 1; y: 1 }
                PathLine { x: root.pw - 1; y: root.ph - 1 }
                PathLine { x: 1;           y: root.ph - 1 }
                PathLine { x: 1;           y: 1 }
            }
        }
    }

    // ── chunk: flow-animation
    NumberAnimation {
        objectName: "flow"
        target: root
        property: "phase"
        from: 5; to: 0                     // one dash period (5 pen widths) per loop; a shrinking offset moves the dashes forward along the path = clockwise
        duration: 300
        loops: Animation.Infinite
        running: root.waiting
    }
}
