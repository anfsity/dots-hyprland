import qs
import qs.modules.common
import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Services.Pam

Scope {
    id: root

    enum ActionEnum { Unlock, Poweroff, Reboot }

    signal shouldReFocus()
    signal unlocked(targetAction: var)
    signal failed()

    // These properties are in the context and not individual lock surfaces
    // so all surfaces can share the same state.
    property string currentText: ""
    property bool unlockInProgress: false
    property bool showFailure: false
    property bool fingerprintsConfigured: false
    property bool sessionLocked: false
    property bool gazeAvailable: false
    property bool faceAuthInProgress: false
    property string faceAuthState: "idle"
    readonly property bool faceUnlockEnabled: gazeAvailable && (Config.options.lock.faceUnlock?.enable ?? true)
    property var targetAction: LockContext.ActionEnum.Unlock
    property bool alsoInhibitIdle: false

    onSessionLockedChanged: {
        if (sessionLocked) tryFaceUnlock();
        else stopFacePam();
    }
    onFaceUnlockEnabledChanged: {
        if (faceUnlockEnabled) tryFaceUnlock();
        else stopFacePam();
    }
    onTargetActionChanged: {
        stopFacePam();
        tryFaceUnlock();
    }
    onShouldReFocus: tryFaceUnlock()

    function resetTargetAction() {
        root.targetAction = LockContext.ActionEnum.Unlock;
    }

    function clearText() {
        root.currentText = "";
    }

    function resetClearTimer() {
        passwordClearTimer.restart();
    }

    function reset() {
        root.resetTargetAction();
        root.clearText();
        root.unlockInProgress = false;
        stopFingerPam();
        stopFacePam();
        tryFaceUnlock();
    }

    Timer {
        id: passwordClearTimer
        interval: 10000
        onTriggered: {
            root.reset();
        }
    }

    onCurrentTextChanged: {
        if (currentText.length > 0) {
            showFailure = false;
            GlobalStates.screenUnlockFailed = false;
        }
        GlobalStates.screenLockContainsCharacters = currentText.length > 0;
        passwordClearTimer.restart();
    }

    function tryUnlock(alsoInhibitIdle = false) {
        if (root.unlockInProgress) return;
        stopFacePam();
        root.alsoInhibitIdle = alsoInhibitIdle;
        root.unlockInProgress = true;
        pam.start();
    }

    function tryFingerUnlock() {
        if (root.fingerprintsConfigured) {
            fingerPam.start();
        }
    }

    function stopFingerPam() {
        if (fingerPam.active) {
            fingerPam.abort();
        }
    }

    function tryFaceUnlock(delay = Config.options.lock.faceUnlock?.startDelayMs ?? 2000) {
        if (!root.sessionLocked || !root.faceUnlockEnabled || root.unlockInProgress
                || root.targetAction !== LockContext.ActionEnum.Unlock
                || facePam.active || faceStartTimer.running) return;
        faceStartTimer.interval = Math.max(0, delay);
        root.faceAuthState = "waiting";
        faceStartTimer.start();
    }

    function retryFaceUnlock() {
        if (!root.sessionLocked || !root.faceUnlockEnabled || root.unlockInProgress
                || root.targetAction !== LockContext.ActionEnum.Unlock || root.faceAuthInProgress) return;
        stopFacePam();
        tryFaceUnlock(0);
    }

    function stopFacePam() {
        faceStartTimer.stop();
        root.faceAuthInProgress = false;
        root.faceAuthState = "idle";
        if (facePam.active) facePam.abort();
    }

    Timer {
        id: faceStartTimer
        onTriggered: {
            if (root.sessionLocked && root.faceUnlockEnabled && !root.unlockInProgress
                    && root.targetAction === LockContext.ActionEnum.Unlock) {
                root.faceAuthInProgress = facePam.start();
                root.faceAuthState = root.faceAuthInProgress ? "scanning" : "unavailable";
            }
        }
    }

    Process {
        id: gazeCheckProc
        running: true
        command: ["sh", "-c", "command -v gaze >/dev/null 2>&1"]
        onExited: (exitCode, exitStatus) => root.gazeAvailable = exitCode === 0
    }

    PamContext {
        id: facePam
        configDirectory: "pam"
        config: "quickshell-face"

        // Confirmation prompts need UI support; fall back to the password instead
        // of answering them automatically or forwarding the user's password.
        onPamMessage: {
            if (this.responseRequired) {
                root.stopFacePam();
                root.faceAuthState = "confirmation";
            }
        }

        onCompleted: result => {
            const wasRunning = root.faceAuthInProgress;
            root.faceAuthInProgress = false;
            if (!wasRunning || !root.sessionLocked || !root.faceUnlockEnabled
                    || root.unlockInProgress || root.targetAction !== LockContext.ActionEnum.Unlock) return;
            if (result === PamResult.Success) {
                root.stopFingerPam();
                root.unlocked(LockContext.ActionEnum.Unlock);
            } else if (result === PamResult.Failed) {
                // A scan can time out long before the user returns to the computer.
                root.tryFaceUnlock(Config.options.lock.faceUnlock?.retryDelayMs ?? 10000);
                root.faceAuthState = "retrying";
            } else {
                root.faceAuthState = "unavailable";
            }
        }
    }

    Process {
        id: fingerprintCheckProc
        running: true
        command: ["bash", "-c", "fprintd-list $(whoami)"]
        stdout: StdioCollector {
            id: fingerprintOutputCollector
            onStreamFinished: {
                root.fingerprintsConfigured = fingerprintOutputCollector.text.includes("Fingerprints for user");
            }
        }
        onExited: (exitCode, exitStatus) => {
            if (exitCode !== 0) {
                // console.warn("[LockContext] fprintd-list command exited with error:", exitCode, exitStatus);
                root.fingerprintsConfigured = false;
            }
        }
    }
    
    PamContext {
        id: pam

        // pam_unix will ask for a response for the password prompt
        onPamMessage: {
            if (this.responseRequired) {
                this.respond(root.currentText);
            }
        }

        // pam_unix won't send any important messages so all we need is the completion status.
        onCompleted: result => {
            if (result == PamResult.Success) {
                root.unlocked(root.targetAction);
                stopFingerPam();
            } else {
                root.clearText();
                root.unlockInProgress = false;
                GlobalStates.screenUnlockFailed = true;
                root.showFailure = true;
                root.tryFaceUnlock();
            }
        }
    }

    PamContext {
        id: fingerPam

        configDirectory: "pam"
        config: "fprintd.conf"

        onCompleted: result => {
            if (result == PamResult.Success) {
                root.unlocked(root.targetAction);
                stopFingerPam();
            } else if (result == PamResult.Error) { // if timeout or etc..
                tryFingerUnlock()
            }
        }
    }
}
