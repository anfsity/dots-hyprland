import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import qs
import qs.modules.common
import qs.modules.common.widgets

Rectangle {
    id: root
    required property LockContext context
    readonly property bool scanning: context.faceAuthInProgress
    readonly property bool needsPassword: context.faceAuthState === "unavailable"
        || context.faceAuthState === "confirmation"
    readonly property color accentColor: Appearance.colors.colPrimary
    readonly property color secondaryColor: Appearance.colors.colOnSurfaceVariant

    visible: context.faceUnlockEnabled && context.sessionLocked
        && context.targetAction === LockContext.ActionEnum.Unlock && !context.unlockInProgress
    implicitWidth: 440
    implicitHeight: content.implicitHeight + 32
    radius: 24
    color: Qt.alpha(Appearance.m3colors.m3surfaceContainer, 1)
    border.width: 1
    border.color: Qt.alpha(root.accentColor, root.scanning ? 0.35 : 0.16)
    Behavior on border.color {
        ColorAnimation {
            duration: 200
        }
    }
    Accessible.role: Accessible.StaticText
    Accessible.name: title.text + ". " + hint.text

    ColumnLayout {
        id: content
        anchors {
            left: parent.left
            right: parent.right
            top: parent.top
            margins: 16
        }
        spacing: 12

        RowLayout {
            Layout.fillWidth: true
            Layout.minimumHeight: 30
            spacing: 8
            Rectangle {
                implicitWidth: 6
                implicitHeight: 6
                radius: 3
                color: root.needsPassword ? root.secondaryColor : root.accentColor
                SequentialAnimation on opacity {
                    running: root.scanning && root.visible
                    loops: Animation.Infinite
                    NumberAnimation {
                        to: 0.35
                        duration: 850
                    }
                    NumberAnimation {
                        to: 1
                        duration: 850
                    }
                    onStopped: opacity = 1
                }
            }
            StyledText {
                Layout.fillWidth: true
                text: "Gaze"
                font.pixelSize: Appearance.font.pixelSize.smaller
                font.weight: Font.DemiBold
                font.letterSpacing: 0.8
                color: root.secondaryColor
            }
            Button {
                id: retryButton
                objectName: "faceRetryButton"
                implicitWidth: retryContent.implicitWidth + 20
                implicitHeight: 30
                visible: !root.scanning && root.context.faceAuthState !== "confirmation"
                text: Translation.tr("Retry face unlock")
                Accessible.name: text
                // Mouse retries leave keyboard focus in the password field.
                focusPolicy: Qt.TabFocus
                onClicked: root.context.retryFaceUnlock()
                background: Rectangle {
                    radius: 15
                    color: Qt.alpha(root.accentColor,
                        retryButton.down ? 0.22 : retryButton.hovered ? 0.16 : 0.09)
                    border.width: retryButton.activeFocus ? 2 : 0
                    border.color: root.accentColor
                    Behavior on color {
                        ColorAnimation {
                            duration: 120
                        }
                    }
                }
                contentItem: RowLayout {
                    id: retryContent
                    spacing: 4
                    MaterialSymbol {
                        text: "refresh"
                        iconSize: 16
                        color: root.accentColor
                    }
                    StyledText {
                        text: Translation.tr("Retry")
                        font.pixelSize: Appearance.font.pixelSize.smaller
                        font.weight: Font.Medium
                        color: root.accentColor
                    }
                }
                HoverHandler {
                    cursorShape: Qt.PointingHandCursor
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 14
            Rectangle {
                id: scanTile
                Layout.alignment: Qt.AlignVCenter
                implicitWidth: root.width < 320 ? 40 : 52
                implicitHeight: implicitWidth
                radius: 16
                color: Qt.alpha(root.accentColor, root.needsPassword ? 0.04 : 0.10)
                border.width: 1
                border.color: Qt.alpha(root.accentColor, 0.18)
                clip: true
                MaterialSymbol {
                    anchors.centerIn: parent
                    text: root.needsPassword ? "lock" : "face"
                    iconSize: root.width < 320 ? 24 : 30
                    color: root.needsPassword ? root.secondaryColor : root.accentColor
                }
                Rectangle {
                    id: scanLine
                    objectName: "faceScanLine"
                    x: 8
                    width: parent.width - 16
                    height: 2
                    radius: 1
                    color: root.accentColor
                    visible: root.scanning
                    SequentialAnimation on y {
                        running: root.scanning && root.visible
                        loops: Animation.Infinite
                        NumberAnimation {
                            from: 10
                            to: scanTile.height - 12
                            duration: 1400
                            easing.type: Easing.InOutSine
                        }
                        NumberAnimation {
                            from: scanTile.height - 12
                            to: 10
                            duration: 1400
                            easing.type: Easing.InOutSine
                        }
                    }
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 5

                StyledText {
                    id: title
                    Layout.fillWidth: true
                    wrapMode: Text.Wrap
                    font.pixelSize: Appearance.font.pixelSize.small
                    font.weight: Font.DemiBold
                    color: Appearance.colors.colOnSurface
                    text: {
                        switch (root.context.faceAuthState) {
                        case "scanning":
                            return Translation.tr("Looking for your face…");
                        case "waiting":
                            return Translation.tr("Face unlock starts shortly");
                        case "retrying":
                            return Translation.tr("Face not recognized");
                        case "unavailable":
                            return Translation.tr("Face unlock unavailable");
                        case "confirmation":
                            return Translation.tr("Use your password to unlock");
                        default:
                            return Translation.tr("Face unlock ready");
                        }
                    }
                }

                StyledText {
                    id: hint
                    Layout.fillWidth: true
                    wrapMode: Text.Wrap
                    font.pixelSize: Appearance.font.pixelSize.smaller
                    color: root.secondaryColor
                    lineHeight: 1.15
                    text: {
                        if (root.scanning)
                            return Translation.tr("Look at the camera, or enter your password");
                        if (root.context.faceAuthState === "retrying")
                            return Translation.tr("Retrying automatically. You can use your password.");
                        if (root.needsPassword)
                            return Translation.tr("Enter your password below to continue");
                        return Translation.tr("You can also enter your password");
                    }
                }
            }
        }
    }
}
