#!/usr/bin/env python3
"""Exercise face unlock with fake PAM replies, without locking or using a camera.

Requires Qt 6 qmltestrunner. An optional argument selects a LockContext.qml file.
Set QMLTESTRUNNER to override the runner executable.
Set FACE_UNLOCK_ARTIFACTS to retain rendered status cards for visual inspection.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

FIXTURES = {
    'imports/qs/qmldir': """module qs
singleton GlobalStates 1.0 GlobalStates.qml
singleton Translation 1.0 Translation.qml
""",
    'imports/qs/GlobalStates.qml': """pragma Singleton
import QtQml
QtObject { property bool screenUnlockFailed: false; property bool screenLockContainsCharacters: false }""",
    'imports/qs/Translation.qml': """pragma Singleton
import QtQml
QtObject { property var messages: ({}); function tr(text) { return messages[text] ?? text; } }""",
    'imports/qs/modules/common/qmldir': """module qs.modules.common
singleton Config 1.0 Config.qml
singleton Appearance 1.0 Appearance.qml
""",
    'imports/qs/modules/common/Appearance.qml': """pragma Singleton
import QtQml
QtObject {
 property var m3colors: ({m3surfaceContainer: "#211a2d"})
 property var colors: ({colPrimary: "#cdb7ff", colOnSurface: "#e7deff", colOnSurfaceVariant: "#cac2d5"})
 property var font: ({pixelSize: {small: 14, smaller: 12}})
}
""",
    'imports/qs/modules/common/widgets/qmldir': """module qs.modules.common.widgets
StyledText 1.0 StyledText.qml
MaterialSymbol 1.0 MaterialSymbol.qml
ToolbarButton 1.0 ToolbarButton.qml
""",
    'imports/qs/modules/common/widgets/StyledText.qml': """import QtQuick
Text { }
""",
    'imports/qs/modules/common/widgets/MaterialSymbol.qml': """import QtQuick
Text { property real iconSize: 24; font.family: "Material Symbols Rounded"; font.pixelSize: iconSize }
""",
    'imports/qs/modules/common/widgets/ToolbarButton.qml': """import QtQuick
import QtQuick.Controls
Button { background: Rectangle { color: \"transparent\"; radius: 18 } }
""",
    'imports/qs/modules/common/Config.qml': """pragma Singleton
import QtQml
QtObject { property var options: ({lock: {faceUnlock: {enable: true, startDelayMs: 5, retryDelayMs: 20}}}) }
""",
    'imports/Quickshell/qmldir': """module Quickshell
Scope 1.0 Scope.qml
""",
    'imports/Quickshell/Scope.qml': """import QtQuick
Item {}""",
    'imports/Quickshell/Io/qmldir': """module Quickshell.Io
Process 1.0 Process.qml
StdioCollector 1.0 StdioCollector.qml
""",
    'imports/Quickshell/Io/Process.qml': """import QtQml
QtObject {
 property bool running: false
 property var command: []
 property QtObject stdout
 signal exited(int exitCode, int exitStatus)
}
""",
    'imports/Quickshell/Io/StdioCollector.qml': """import QtQml
QtObject { property string text: ""; signal streamFinished() }""",
    'imports/Quickshell/Services/Pam/qmldir': """module Quickshell.Services.Pam
PamContext 1.0 PamContext.qml
PamResult 1.0 PamResult.qml
""",
    'imports/Quickshell/Services/Pam/PamResult.qml': """import QtQml
QtObject { enum Result { Success, Failed, Error, MaxTries } }""",
    'imports/Quickshell/Services/Pam/PamContext.qml': """import QtQml
QtObject {
 objectName: config
 property string config: "login"
 property string configDirectory: "/etc/pam.d"
 property bool active: false
 property bool responseRequired: false
 property int starts: 0
 property int aborts: 0
 signal completed(int result)
 signal pamMessage()
 function start() { active = true; starts++; return true; }
 function abort() { active = false; aborts++; }
 function respond(value) { throw new Error("Face prompts must never be answered automatically"); }
 function finish(result) { active = false; completed(result); }
}
""",
    'tst_face.qml': """import QtQuick
import QtTest
import Quickshell.Services.Pam
import qs.modules.common

TestCase {
 id: testCase
 name: "FaceUnlock"
 when: windowShown
 property var context
 property var face
 property var password
 Component { id: factory; LockContext {} }
 SignalSpy { id: unlocked; signalName: "unlocked" }
 function init() {
     Config.options = {lock: {faceUnlock: {enable: true, startDelayMs: 5, retryDelayMs: 20}}};
     context = createTemporaryObject(factory, testCase);
     verify(context !== null);
     // QtObject children are in data, not Item.children.
     for (const child of context.data) {
         if (child.objectName === "quickshell-face") face = child;
         if (child.objectName === "login") password = child;
     }
     verify(face !== null && password !== null);
     context.gazeAvailable = true;
     unlocked.target = context;
     unlocked.clear();
 }
 function cleanup() {
     context.sessionLocked = false;
     unlocked.target = null;
 }
 function beginScan() {
     context.sessionLocked = true;
     tryCompare(face, "active", true);
 }
 function test_visible_scan_states() {
     compare(context.faceAuthState, "idle");
     context.sessionLocked = true;
     compare(context.faceAuthState, "waiting");
     tryCompare(context, "faceAuthState", "scanning");
     face.finish(PamResult.Failed);
     compare(context.faceAuthState, "retrying");
     tryCompare(context, "faceAuthState", "scanning");
     face.finish(PamResult.Error);
     compare(context.faceAuthState, "unavailable");
 }
 function test_retry_skips_delay_without_duplicate_scan() {
     Config.options = {lock: {faceUnlock: {enable: true, startDelayMs: 5000, retryDelayMs: 5000}}};
     context.sessionLocked = true;
     compare(context.faceAuthState, "waiting");
     context.retryFaceUnlock();
     tryCompare(face, "starts", 1);
     context.retryFaceUnlock();
     compare(face.starts, 1);
     face.finish(PamResult.Failed);
     compare(context.faceAuthState, "retrying");
     context.retryFaceUnlock();
     tryCompare(face, "starts", 2);
 }
 function test_retry_error_and_guard_power_action() {
     beginScan();
     face.finish(PamResult.Error);
     compare(context.faceAuthState, "unavailable");
     context.retryFaceUnlock();
     tryCompare(face, "starts", 2);
     context.targetAction = LockContext.ActionEnum.Poweroff;
     context.retryFaceUnlock();
     wait(30);
     compare(face.starts, 2);
 }
 function test_requires_secure_lock() {
     wait(30);
     compare(face.starts, 0);
     beginScan();
     compare(face.starts, 1);
 }
 function test_password_remains_available() {
     beginScan();
     compare(context.unlockInProgress, false);
     context.currentText = "password";
     context.tryUnlock();
     compare(face.active, false);
     compare(password.active, true);
     face.finish(PamResult.Success);
     compare(unlocked.count, 0);
     password.finish(PamResult.Success);
     compare(unlocked.count, 1);
 }
 function test_only_success_unlocks() {
     beginScan();
     face.finish(PamResult.Failed);
     compare(unlocked.count, 0);
     tryCompare(face, "starts", 2);
     face.finish(PamResult.Success);
     compare(unlocked.count, 1);
     compare(unlocked.signalArguments[0][0], LockContext.ActionEnum.Unlock);
 }
 function test_no_scan_after_unlock() {
     beginScan();
     context.sessionLocked = false;
     compare(face.active, false);
     face.finish(PamResult.Success);
     wait(30);
     compare(unlocked.count, 0);
     compare(face.starts, 1);
 }
 function test_missing_gaze() {
     context.gazeAvailable = false;
     context.sessionLocked = true;
     wait(30);
     compare(face.starts, 0);
 }
 function test_disable_feature() {
     Config.options = {lock: {faceUnlock: {enable: false}}};
     context.sessionLocked = true;
     wait(30);
     compare(face.starts, 0);
 }
 function test_cannot_authorize_power_action() {
     beginScan();
     context.targetAction = LockContext.ActionEnum.Poweroff;
     compare(face.active, false);
     face.finish(PamResult.Success);
     compare(unlocked.count, 0);
 }
 function test_does_not_answer_confirmation() {
     beginScan();
     face.responseRequired = true;
     face.pamMessage();
     compare(face.active, false);
     compare(context.faceAuthInProgress, false);
     compare(context.faceAuthState, "confirmation");
     face.finish(PamResult.Success);
     compare(unlocked.count, 0);
 }
 function test_error_does_not_loop() {
     beginScan();
     face.finish(PamResult.Error);
     wait(40);
     compare(face.starts, 1);
     context.shouldReFocus();
     tryCompare(face, "starts", 2);
 }
 function test_failed_password_restarts_face() {
     beginScan();
     context.tryUnlock();
     password.finish(PamResult.Failed);
     compare(context.showFailure, true);
     tryCompare(face, "starts", 2);
     compare(context.unlockInProgress, false);
 }
}
""",
    'tst_face_ui.qml': """import QtQuick
import QtTest
import Quickshell.Services.Pam
import qs
import qs.modules.common

TestCase {
 id: testCase
 name: "FaceUnlockUI"
 when: windowShown
 visible: true
 width: 480
 height: 400
 property var context
 property var card
 Component { id: contextFactory; LockContext {} }
 Component { id: cardFactory; FaceAuthStatus {} }
 function init() {
     failOnWarning(/.*/);
     Config.options = {lock: {faceUnlock: {enable: true, startDelayMs: 5000, retryDelayMs: 5000}}};
     context = createTemporaryObject(contextFactory, testCase);
     context.gazeAvailable = true;
     context.sessionLocked = true;
     card = createTemporaryObject(cardFactory, testCase, {context: context, width: 440});
     verify(card !== null);
 }
 function cleanup() {
     context.sessionLocked = false;
     card.destroy();
     wait(0);
 }
 function test_visibility_and_power_action() {
     verify(card.visible);
     context.targetAction = LockContext.ActionEnum.Poweroff;
     verify(!card.visible);
     context.targetAction = LockContext.ActionEnum.Unlock;
     verify(card.visible);
     context.tryUnlock();
     verify(!card.visible);
 }
 function test_hidden_when_disabled_or_unlocked() {
     context.gazeAvailable = false;
     verify(!card.visible);
     context.gazeAvailable = true;
     verify(card.visible);
     context.sessionLocked = false;
     verify(!card.visible);
 }
 function test_retry_button_starts_scan() {
     const retry = findChild(card, "faceRetryButton");
     verify(retry.visible);
     mouseClick(retry);
     tryCompare(context, "faceAuthState", "scanning");
     verify(!retry.visible);
     context.stopFacePam();
     context.faceAuthState = "confirmation";
     verify(!retry.visible);
     verify(card.needsPassword);
 }
 function test_scan_animation_and_opaque_background() {
     context.retryFaceUnlock();
     tryCompare(context, "faceAuthState", "scanning");
     const line = findChild(card, "faceScanLine");
     verify(line.visible);
     const initialY = line.y;
     wait(120);
     verify(line.y !== initialY);
     compare(card.color.a, 1);
     compare(grabImage(card).alpha(card.width / 2, card.height - 8), 255);
     context.stopFacePam();
     verify(!line.visible);
 }
 function test_render_status_cards() {
     if (!ARTIFACT_DIRECTORY) return;
     Translation.messages = TRANSLATIONS;
     for (const state of ["waiting", "scanning", "retrying", "unavailable", "confirmation"]) {
         context.faceAuthState = state;
         context.faceAuthInProgress = state === "scanning";
         wait(250);
         grabImage(card).save(ARTIFACT_DIRECTORY + "/gaze-" + state + ".png");
     }
     Translation.messages = {};
 }
 function test_narrow_and_long_text_layout() {
     card.width = 240;
     const states = ["waiting", "scanning", "retrying", "unavailable", "confirmation"];
     for (const state of states) {
         context.faceAuthState = state;
         context.faceAuthInProgress = state === "scanning";
         wait(20);
         verify(card.height > 40);
         verify(card.height < 240);
         function checkBounds(item) {
             for (const child of item.children) {
                 if (!child.visible || child.width <= 0) continue;
                 const pos = child.mapToItem(card, 0, 0);
                 verify(pos.x >= -1 && pos.x + child.width <= card.width + 1,
                        state + ": horizontal overflow");
                 verify(pos.y >= -1 && pos.y + child.height <= card.height + 1,
                        state + ": vertical overflow");
                 checkBounds(child);
             }
         }
         checkBounds(card);
     }
 }
}
""",
}


def main():
    source = (Path(sys.argv[1]) if len(sys.argv) > 1 else
              Path(__file__).resolve().parents[1] /
              "dots/.config/quickshell/ii/modules/common/panels/lock/LockContext.qml")
    runner = os.environ.get("QMLTESTRUNNER") or next(
        (candidate for candidate in (
            shutil.which("qmltestrunner6"),
            "/usr/lib/qt6/bin/qmltestrunner",
            "/usr/lib64/qt6/bin/qmltestrunner",
        ) if candidate and Path(candidate).is_file()), None)
    if not runner:
        raise SystemExit("Install Qt 6 qmltestrunner or set QMLTESTRUNNER.")
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software",
               QT_QUICK_CONTROLS_STYLE="Basic", QT_QPA_PLATFORMTHEME="", QT_IM_MODULE="")
    artifacts = os.environ.get("FACE_UNLOCK_ARTIFACTS", "")
    if artifacts:
        artifacts = str(Path(artifacts).resolve())
        Path(artifacts).mkdir(parents=True, exist_ok=True)
    translations = json.loads((Path(__file__).resolve().parents[1] /
                              "dots/.config/quickshell/ii/translations/zh_CN.json").read_text())
    with tempfile.TemporaryDirectory(prefix="quickshell-face-test-") as directory:
        root = Path(directory)
        for name, content in FIXTURES.items():
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            if name == 'tst_face_ui.qml':
                content = content.replace('ARTIFACT_DIRECTORY', json.dumps(artifacts))
                content = content.replace('TRANSLATIONS', '(' + json.dumps(translations, ensure_ascii=False) + ')')
            target.write_text(content)
        shutil.copy(source, root / "LockContext.qml")
        shutil.copy(source.with_name("FaceAuthStatus.qml"), root / "FaceAuthStatus.qml")
        subprocess.run([runner, "-input", str(root), "-import", str(root / "imports")],
                       env=env, check=True, timeout=40)


if __name__ == "__main__":
    main()
