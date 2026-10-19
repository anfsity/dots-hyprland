#!/usr/bin/env python3
"""Exercise face unlock with fake PAM replies, without locking or using a camera.

Requires Qt 6 qmltestrunner. An optional argument selects a LockContext.qml file.
Set QMLTESTRUNNER to override the runner executable.
"""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

FIXTURES = {
    'imports/qs/qmldir': """module qs
singleton GlobalStates 1.0 GlobalStates.qml
""",
    'imports/qs/GlobalStates.qml': """pragma Singleton
import QtQml
QtObject { property bool screenUnlockFailed: false; property bool screenLockContainsCharacters: false }""",
    'imports/qs/modules/common/qmldir': """module qs.modules.common
singleton Config 1.0 Config.qml
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
               QT_QPA_PLATFORMTHEME="", QT_IM_MODULE="")
    with tempfile.TemporaryDirectory(prefix="quickshell-face-test-") as directory:
        root = Path(directory)
        for name, content in FIXTURES.items():
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        shutil.copy(source, root / "LockContext.qml")
        subprocess.run([runner, "-input", str(root), "-import", str(root / "imports")],
                       env=env, check=True, timeout=40)


if __name__ == "__main__":
    main()
