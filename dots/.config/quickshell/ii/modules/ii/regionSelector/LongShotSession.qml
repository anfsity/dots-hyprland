pragma ComponentBehavior: Bound
import qs
import qs.modules.common
import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland

Scope {
    id: root
    readonly property bool active: captureProc.running || startDelay.running
    property string phase: "idle"
    property string captureStatus: "waiting"
    property var targetScreen: null
    property var bounds: ({x: 0, y: 0, width: 0, height: 0})
    property string region: ""
    property int frames: 0
    property int imageWidth: 0
    property int imageHeight: 0
    property int frameHeight: 0
    property real quality: 0
    property string previewSource: ""
    property int previewRevision: -1
    property string output: ""
    property string detail: ""
    property bool cancelled: false
    property bool automatic: false
    property bool autoAvailable: true

    function start(region, targetScreen, bounds) {
        if (root.active) return;
        root.region = region;
        root.targetScreen = targetScreen;
        root.bounds = bounds;
        root.frames = 0;
        root.imageWidth = 0;
        root.imageHeight = 0;
        root.frameHeight = 0;
        root.quality = 0;
        root.previewSource = "";
        root.previewRevision = -1;
        root.output = "";
        root.detail = "";
        root.cancelled = false;
        root.automatic = false;
        root.autoAvailable = true;
        root.captureStatus = "waiting";
        root.phase = "starting";
        startDelay.start();
    }

    function finish() {
        if (!root.active || root.phase === "saving") return;
        if (startDelay.running) { cancel(); return; }
        root.phase = "saving";
        captureProc.write("finish\n");
    }

    function togglePause() {
        setPaused(root.phase !== "paused");
    }

    function setPaused(paused) {
        if (!captureProc.running || !["capturing", "paused"].includes(root.phase)) return;
        captureProc.write(paused ? "pause\n" : "resume\n");
    }

    function toggleAutomatic() {
        if (!captureProc.running || !root.autoAvailable || !["capturing", "paused"].includes(root.phase)) return;
        captureProc.write(root.automatic ? "manual\n" : "auto\n");
    }

    function interruptAutomatic() {
        if (captureProc.running && root.automatic && root.phase === "capturing")
            captureProc.write("interrupt\n");
    }

    function cancel() {
        if (root.phase === "saving") return;
        root.cancelled = true;
        startDelay.stop();
        if (captureProc.running) captureProc.write("cancel\n");
        root.phase = "idle";
    }

    function dismissResult() {
        if (!root.active) root.phase = "idle";
    }

    function acceptEvent(update) {
        if (update.event === "progress") {
            root.frames = update.frames;
            root.imageWidth = update.width;
            root.imageHeight = update.height;
            root.frameHeight = update.frameHeight;
            root.quality = update.confidence;
            root.captureStatus = update.status;
            root.automatic = update.automatic ?? false;
            root.autoAvailable = update.autoAvailable ?? true;
            root.detail = update.message ? Translation.tr(update.message) : "";
            if (root.phase !== "saving" && !root.cancelled)
                root.phase = update.status === "paused" ? "paused" : "capturing";
            if (update.preview && update.revision !== root.previewRevision) {
                root.previewSource = "file://" + update.preview;
                root.previewRevision = update.revision;
            }
        } else if (update.event === "saving") {
            root.phase = "saving";
        } else if (update.event === "done") {
            root.output = update.output;
            root.phase = "done";
            root.detail = update.truncated ? Translation.tr("Saved through the last aligned frame.")
                : update.limited ? Translation.tr("Capture limit reached. Your screenshot has been saved.")
                : update.copied ? Translation.tr("Saved and copied to clipboard.")
                : Translation.tr("Saved. Clipboard copy was unavailable.");
        } else if (update.event === "error") {
            root.phase = "error";
            root.detail = Translation.tr(update.message);
        } else if (update.event === "cancelled") {
            root.cancelled = true;
            root.phase = "idle";
        }
    }

    Timer {
        id: startDelay
        interval: Config.options.screenSnip.longShot?.settleDelay ?? 300
        onTriggered: captureProc.running = true
    }

    Process {
        id: captureProc
        stdinEnabled: true
        command: [Directories.longshotScriptPath, "--region", root.region,
            "--control-stdin", "--settle-delay", "0",
            "--preview-dir", `${Directories.cache}/media/longshot`.replace(/^file:\/\//, "")]
        stdout: SplitParser {
            onRead: line => {
                try { root.acceptEvent(JSON.parse(line)); }
                catch (error) { console.warn("[Long screenshot]", error, line); }
            }
        }
        stderr: SplitParser { onRead: line => console.warn("[Long screenshot]", line) }
        onExited: (exitCode, exitStatus) => {
            if (root.cancelled) root.phase = "idle";
            else if (root.phase !== "done" && root.phase !== "error") {
                root.phase = "error";
                root.detail = Translation.tr("Capture ended unexpectedly. Try selecting the region again.");
            }
        }
    }

    // Never draw the controller inside captured pixels. Prefer a full preview
    // beside the selection, then a compact controller above/below it.
    function place(width, height) {
        if (!root.targetScreen) return null;
        const sw = root.targetScreen.width, sh = root.targetScreen.height, b = root.bounds;
        if (width + 24 > sw || height + 24 > sh) return null;
        const clampX = x => Math.max(12, Math.min(sw - width - 12, x));
        const clampY = y => Math.max(12, Math.min(sh - height - 12, y));
        const centerX = clampX(b.x + (b.width - width) / 2);
        const centerY = clampY(b.y + (b.height - height) / 2);
        const candidates = [
            {x: b.x + b.width + 16, y: centerY},
            {x: b.x - width - 16, y: centerY},
            {x: centerX, y: b.y - height - 16},
            {x: centerX, y: b.y + b.height + 16}
        ];
        return candidates.find(p => p.x >= 12 && p.y >= 12
            && p.x + width <= sw - 12 && p.y + height <= sh - 12) ?? null;
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
        readonly property bool complete: root.phase === "done" || root.phase === "error"
        readonly property var fullPosition: root.place(332, 550)
        readonly property var compactPosition: root.place(332, 210)
        readonly property var position: complete && root.targetScreen
            ? {x: Math.max(12, root.targetScreen.width - 356), y: Math.max(12, (root.targetScreen.height - 550) / 2)}
            : fullPosition ?? compactPosition
        visible: root.phase !== "idle" && position !== null
        mask: Region { item: panel }

        LongShotPanel {
            id: panel
            x: controlsWindow.position?.x ?? 12
            y: controlsWindow.position?.y ?? 12
            width: 332
            height: implicitHeight
            compact: !controlsWindow.complete && controlsWindow.fullPosition === null
            phase: root.phase
            automatic: root.automatic
            autoAvailable: root.autoAvailable
            captureStatus: root.captureStatus
            frames: root.frames
            imageWidth: root.imageWidth
            imageHeight: root.imageHeight
            frameHeight: root.frameHeight
            quality: root.quality
            previewSource: root.previewSource
            detail: root.detail
            tr: text => Translation.tr(text)
            // This is a standalone surface, not an overlay on another themed layer.
            surfaceColor: Appearance.m3colors.m3surfaceContainer
            surfaceVariant: Appearance.m3colors.m3surfaceContainerLowest
            textColor: Appearance.m3colors.m3onSurface
            mutedColor: Appearance.m3colors.m3onSurfaceVariant
            accentColor: Appearance.colors.colPrimary
            accentTextColor: Appearance.colors.colOnPrimary
            warningColor: Appearance.colors.colError
            fontFamily: Appearance.font.family.main
            iconFamily: Appearance.font.family.iconMaterial
            onFinishRequested: root.finish()
            onPauseRequested: resume => root.setPaused(!resume)
            onAutoRequested: root.toggleAutomatic()
            onCancelRequested: root.cancel()
            onCloseRequested: root.phase = "idle"
            onOpenRequested: if (root.output) Quickshell.execDetached(["xdg-open", root.output])
        }
    }
}
