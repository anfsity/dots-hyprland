pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// A presentation-only view: no capture process or desktop state is created here.
Rectangle {
    id: root
    property string phase: "capturing"
    property string captureStatus: "waiting"
    property int frames: 0
    property int imageWidth: 0
    property int imageHeight: 0
    property int frameHeight: 0
    property real quality: 0
    property url previewSource
    property string detail: ""
    property bool compact: false
    property bool followTail: true
    property var tr: text => text
    property color surfaceColor: "#211f26"
    property color surfaceVariant: "#302d37"
    property color textColor: "#e7e0ec"
    property color mutedColor: "#cac4d0"
    property color accentColor: "#d0bcff"
    property color accentTextColor: "#381e72"
    property color warningColor: "#ffcc80"
    property string fontFamily: "Google Sans Flex"
    property string iconFamily: "Material Symbols Rounded"
    readonly property bool complete: phase === "done" || phase === "error"
    readonly property bool uncertain: ["no-overlap", "ambiguous", "backtracking"].includes(captureStatus)
    readonly property color statusColor: uncertain || phase === "error" ? warningColor : accentColor
    readonly property string phaseLabel: {
        if (phase === "done") return root.tr("Saved");
        if (phase === "error") return root.tr("Capture stopped");
        if (phase === "saving") return root.tr("Saving…");
        if (phase === "paused") return root.tr("Paused");
        if (phase === "starting") return root.tr("Getting ready…");
        return root.tr("Capturing");
    }
    readonly property string guidance: {
        if (root.detail) return root.detail;
        if (phase === "paused") return root.tr("Resume from the last captured position.");
        if (captureStatus === "backtracking") return root.tr("Scroll down past the last captured position to continue.");
        if (captureStatus === "ambiguous") return root.tr("Repeated content detected. Scroll back, then continue slowly.");
        if (captureStatus === "no-overlap") return root.tr("Overlap lost. Scroll back until the preview starts growing again.");
        if (phase === "saving") return root.tr("Preparing your screenshot…");
        if (phase === "starting") return root.tr("Keep the selected window in place.");
        return root.tr("Scroll slowly. Press Super+Shift+S to finish.");
    }
    signal finishRequested()
    signal pauseRequested()
    signal cancelRequested()
    signal openRequested()
    signal closeRequested()

    implicitWidth: 332
    implicitHeight: content.implicitHeight + (compact ? 24 : 32)
    radius: compact ? 20 : 24
    color: surfaceColor
    border.width: 1
    border.color: Qt.alpha(textColor, 0.12)
    onPhaseChanged: { if (phase === "starting") followTail = true; }

    component Label: Text {
        color: root.textColor
        font.family: root.fontFamily
        font.pixelSize: 13
        renderType: Text.NativeRendering
    }
    component Icon: Text {
        color: root.accentColor
        font.family: root.iconFamily
        font.pixelSize: 20
        renderType: Text.NativeRendering
    }
    component Action: Button {
        id: action
        property string symbol
        property bool primary: false
        implicitHeight: 36
        implicitWidth: row.implicitWidth + 22
        opacity: enabled ? 1 : 0.4
        background: Rectangle {
            radius: 18
            color: action.primary ? root.accentColor :
                   Qt.alpha(root.textColor, action.down ? 0.16 : action.hovered ? 0.10 : 0.05)
        }
        contentItem: RowLayout {
            id: row
            spacing: 5
            Icon {
                text: action.symbol
                color: action.primary ? root.accentTextColor : root.textColor
                font.pixelSize: 18
            }
            Label {
                visible: action.text.length > 0
                text: action.text
                font.weight: Font.Medium
                color: action.primary ? root.accentTextColor : root.textColor
            }
        }
        HoverHandler { cursorShape: Qt.PointingHandCursor }
        ToolTip.visible: hovered && text.length === 0
        ToolTip.text: Accessible.name
    }

    ColumnLayout {
        id: content
        anchors { left: parent.left; right: parent.right; top: parent.top; margins: root.compact ? 12 : 16 }
        spacing: root.compact ? 10 : 14
        RowLayout {
            Layout.fillWidth: true
            spacing: 9
            Icon { text: "screenshot_monitor"; font.pixelSize: 23 }
            Label {
                Layout.fillWidth: true
                text: root.tr("Long screenshot")
                font.pixelSize: 15
                font.weight: Font.DemiBold
            }
            Rectangle {
                width: badgeRow.implicitWidth + 16
                height: 26
                radius: 13
                color: Qt.alpha(root.statusColor, 0.13)
                Row {
                    id: badgeRow
                    anchors.centerIn: parent
                    spacing: 6
                    Rectangle {
                        id: captureDot
                        width: 5; height: 5; radius: 3
                        anchors.verticalCenter: parent.verticalCenter
                        color: root.statusColor
                        SequentialAnimation on opacity {
                            running: root.phase === "capturing" && !root.uncertain && root.visible
                            loops: Animation.Infinite
                            NumberAnimation { to: 0.35; duration: 850 }
                            NumberAnimation { to: 1; duration: 850 }
                            onStopped: captureDot.opacity = 1
                        }
                    }
                    Label { text: root.phaseLabel; color: root.statusColor; font.pixelSize: 11 }
                }
            }
        }
        Rectangle {
            id: previewPane
            objectName: "previewPane"
            Layout.fillWidth: true
            Layout.preferredHeight: 236
            visible: !root.compact
            radius: 14
            color: root.surfaceVariant
            border.width: 1
            border.color: Qt.alpha(root.textColor, 0.06)
            Flickable {
                id: previewFlick
                objectName: "previewFlick"
                anchors { fill: parent; margins: 8 }
                clip: true
                contentWidth: width
                contentHeight: Math.max(height, previewImage.height)
                boundsBehavior: Flickable.StopAtBounds
                onMovementStarted: { root.followTail = false; tailAnimation.stop(); }
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                Image {
                    id: previewImage
                    objectName: "previewImage"
                    width: previewFlick.width
                    height: sourceSize.width > 0 ? width * sourceSize.height / sourceSize.width : 0
                    source: root.previewSource
                    cache: false
                    asynchronous: true
                    retainWhileLoading: true
                    smooth: true
                    mipmap: true
                    function showLatest() {
                        if (root.followTail && status === Image.Ready) {
                            tailAnimation.to = Math.max(0, previewFlick.contentHeight - previewFlick.height);
                            tailAnimation.restart();
                        }
                    }
                    onStatusChanged: if (status === Image.Ready) Qt.callLater(showLatest)
                    onHeightChanged: Qt.callLater(showLatest)
                    Rectangle {
                        width: parent.width
                        height: root.imageHeight > 0 ? Math.min(parent.height, parent.height * root.frameHeight / root.imageHeight) : 0
                        anchors.bottom: parent.bottom
                        color: "transparent"
                        border.width: 2
                        border.color: root.accentColor
                        visible: !root.complete && root.imageHeight > root.frameHeight
                    }
                }
                NumberAnimation {
                    id: tailAnimation
                    target: previewFlick
                    property: "contentY"
                    duration: 180
                    easing.type: Easing.OutCubic
                }
            }
            Column {
                anchors.centerIn: parent
                spacing: 8
                visible: root.previewSource.toString().length === 0
                Icon { anchors.horizontalCenter: parent.horizontalCenter; text: "panorama_vertical"; font.pixelSize: 32 }
                Label { text: root.tr("Your capture will appear here"); color: root.mutedColor; font.pixelSize: 12 }
            }
            Action {
                anchors { right: parent.right; bottom: parent.bottom; margins: 12 }
                visible: !root.followTail && !root.complete
                symbol: "vertical_align_bottom"
                Accessible.name: root.tr("Follow latest capture")
                onClicked: { root.followTail = true; previewImage.showLatest(); }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            Label {
                Layout.fillWidth: true
                text: root.imageWidth > 0 ? "%1 × %2".arg(root.imageWidth).arg(root.imageHeight) : "—"
                font.pixelSize: root.compact ? 15 : 20
                font.weight: Font.DemiBold
            }
            Label { text: root.tr("%1 frames").arg(root.frames); color: root.mutedColor; font.pixelSize: 12 }
        }
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 7
            Rectangle {
                Layout.fillWidth: true
                height: 3
                radius: 2
                color: Qt.alpha(root.textColor, 0.09)
                visible: !root.complete
                Rectangle {
                    width: parent.width * Math.max(0.03, Math.min(1, root.quality))
                    height: parent.height
                    radius: 2
                    color: root.statusColor
                    Behavior on width { NumberAnimation { duration: 180 } }
                    Behavior on color { ColorAnimation { duration: 150 } }
                }
            }
            Label {
                objectName: "guidance"
                Layout.fillWidth: true
                text: root.guidance
                color: root.uncertain || root.phase === "error" ? root.warningColor : root.mutedColor
                wrapMode: Text.WordWrap
                font.pixelSize: 12
                maximumLineCount: root.compact ? 2 : 3
                elide: Text.ElideRight
            }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 7
            Action {
                objectName: "cancelButton"
                symbol: "close"
                Accessible.name: root.tr("Cancel")
                visible: !root.complete
                enabled: root.phase !== "saving"
                onClicked: root.cancelRequested()
            }
            Action {
                objectName: "pauseButton"
                text: root.phase === "paused" ? root.tr("Resume") : root.tr("Pause")
                symbol: root.phase === "paused" ? "play_arrow" : "pause"
                visible: !root.complete
                enabled: root.phase === "capturing" || root.phase === "paused"
                onClicked: root.pauseRequested()
            }
            Action {
                objectName: "closeButton"
                text: root.tr("Close")
                symbol: "close"
                visible: root.complete
                onClicked: root.closeRequested()
            }
            Item { Layout.fillWidth: true }
            Action {
                objectName: "finishButton"
                text: root.tr("Finish")
                symbol: "check"
                primary: true
                visible: !root.complete
                enabled: root.frames > 1 && root.phase !== "saving"
                onClicked: root.finishRequested()
            }
            Action {
                objectName: "openButton"
                text: root.tr("Open image")
                symbol: "open_in_new"
                primary: true
                visible: root.phase === "done"
                onClicked: root.openRequested()
            }
        }
    }
}
