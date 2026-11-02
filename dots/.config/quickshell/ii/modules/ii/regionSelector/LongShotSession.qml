pragma ComponentBehavior: Bound
import qs
import qs.modules.common
import qs.modules.common.widgets
import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import Quickshell.Wayland

Scope {
    id: root
    readonly property bool active: captureProc.running || startDelay.running
    property bool finishing: false
    property var targetScreen: null
    property var bounds: ({x: 0, y: 0, width: 0, height: 0})
    property string region: ""
    property int frames: 0
    property int imageHeight: 0
    property string message: ""

    function start(region, targetScreen, bounds) {
        if (root.active) return;
        root.region = region;
        root.targetScreen = targetScreen;
        root.bounds = bounds;
        root.frames = 0;
        root.imageHeight = 0;
        root.finishing = false;
        root.message = Translation.tr("Scroll down manually; Super+Shift+S to finish");
        startDelay.start();
    }

    function finish() {
        if (!root.active || root.finishing) return;
        if (startDelay.running) {
            startDelay.stop();
            return;
        }
        root.finishing = true;
        captureProc.write("finish\n");
    }

    function cancel() {
        if (!root.active || root.finishing) return;
        if (startDelay.running) {
            startDelay.stop();
            return;
        }
        root.finishing = true;
        captureProc.write("cancel\n");
    }

    Timer {
        id: startDelay
        interval: 350
        onTriggered: captureProc.running = true
    }

    Process {
        id: captureProc
        stdinEnabled: true
        command: [Directories.longshotScriptPath, "--region", root.region, "--control-stdin"]
        stdout: SplitParser {
            onRead: line => {
                try {
                    const update = JSON.parse(line);
                    if (update.event === "progress") {
                        root.frames = update.frames;
                        root.imageHeight = update.height;
                        root.message = update.warning
                            ? Translation.tr("Return to the last captured view, then scroll down slowly")
                            : Translation.tr("Scroll down manually; Super+Shift+S to finish");
                    } else if (update.event === "saving" || update.event === "done" || update.event === "error") {
                        root.finishing = true;
                    }
                } catch (error) {
                    console.warn("[Long screenshot]", line);
                }
            }
        }
        stderr: SplitParser {
            onRead: line => console.warn("[Long screenshot]", line)
        }
        onExited: root.finishing = false
    }

    PanelWindow {
        id: controlsWindow
        screen: root.targetScreen
        color: "transparent"
        exclusionMode: ExclusionMode.Ignore
        WlrLayershell.namespace: "quickshell:longshotControls"
        WlrLayershell.layer: WlrLayer.Overlay
        WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
        anchors { left: true; right: true; top: true; bottom: true }

        // Keep controls outside the capture. Full-screen selections use the shortcut.
        readonly property var position: {
            if (!root.targetScreen) return null;
            const screenWidth = root.targetScreen.width;
            const screenHeight = root.targetScreen.height;
            const w = controls.width + 24;
            const h = controls.height + 24;
            if (screenWidth < w || screenHeight < h) return null;
            const b = root.bounds;
            const candidates = [
                {x: (screenWidth - w) / 2, y: screenHeight - h},
                {x: (screenWidth - w) / 2, y: 0},
                {x: 0, y: (screenHeight - h) / 2},
                {x: screenWidth - w, y: (screenHeight - h) / 2}
            ];
            return candidates.find(p => p.x + w <= b.x || p.x >= b.x + b.width
                || p.y + h <= b.y || p.y >= b.y + b.height) ?? null;
        }
        visible: captureProc.running && !root.finishing && root.frames > 0 && position !== null
        mask: Region { item: controls }

        Rectangle {
            id: controls
            x: (controlsWindow.position?.x ?? 0) + 12
            y: (controlsWindow.position?.y ?? 0) + 12
            width: 500
            height: content.implicitHeight + 24
            radius: 20
            color: Appearance.colors.colSurfaceContainer

            ColumnLayout {
                id: content
                anchors { fill: parent; margins: 12 }
                spacing: 8
                StyledText {
                    Layout.fillWidth: true
                    text: root.message
                    wrapMode: Text.WordWrap
                }
                RowLayout {
                    Layout.fillWidth: true
                    StyledText {
                        Layout.fillWidth: true
                        text: Translation.tr("%1 frames · %2 px").arg(root.frames).arg(root.imageHeight)
                    }
                    ToolbarTabButton {
                        materialSymbol: "check"
                        text: Translation.tr("Finish")
                        current: false
                        onClicked: root.finish()
                    }
                    ToolbarTabButton {
                        materialSymbol: "close"
                        text: Translation.tr("Cancel")
                        current: false
                        onClicked: root.cancel()
                    }
                }
            }
        }
    }
}
