pragma ComponentBehavior: Bound
import qs
import qs.modules.common
import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Hyprland

Scope {
    id: root

    function dismiss() {
        GlobalStates.regionSelectorOpen = false
    }

    property var action: RegionSelection.SnipAction.Copy
    property var selectionMode: RegionSelection.SelectionMode.RectCorners
    
    Variants {
        model: Quickshell.screens
        delegate: Loader {
            id: regionSelectorLoader
            required property var modelData
            active: GlobalStates.regionSelectorOpen

            sourceComponent: RegionSelection {
                screen: regionSelectorLoader.modelData
                onDismiss: root.dismiss()
                onLongshotRequested: (region, targetScreen, bounds) => longshotSession.start(region, targetScreen, bounds)
                action: root.action
                selectionMode: root.selectionMode
            }
        }
    }

    function screenshot() {
        if (longshotSession.active) {
            longshotSession.finish();
            return;
        }
        longshotSession.dismissResult();
        root.action = RegionSelection.SnipAction.Copy
        root.selectionMode = RegionSelection.SelectionMode.RectCorners
        GlobalStates.regionSelectorOpen = true
    }

    function search() {
        longshotSession.cancel()
        root.action = RegionSelection.SnipAction.Search
        if (Config.options.search.imageSearch.useCircleSelection) {
            root.selectionMode = RegionSelection.SelectionMode.Circle
        } else {
            root.selectionMode = RegionSelection.SelectionMode.RectCorners
        }
        GlobalStates.regionSelectorOpen = true
    }

    function ocr() {
        longshotSession.cancel()
        root.action = RegionSelection.SnipAction.CharRecognition
        root.selectionMode = RegionSelection.SelectionMode.RectCorners
        GlobalStates.regionSelectorOpen = true
    }

    function record() {
        longshotSession.cancel()
        root.action = RegionSelection.SnipAction.Record
        root.selectionMode = RegionSelection.SelectionMode.RectCorners
        // If already open then re-trigger to stop recording
        if (GlobalStates.regionSelectorOpen) GlobalStates.regionSelectorOpen = false
        GlobalStates.regionSelectorOpen = true
    }

    function recordWithSound() {
        longshotSession.cancel()
        root.action = RegionSelection.SnipAction.RecordWithSound
        root.selectionMode = RegionSelection.SelectionMode.RectCorners
        // If already open then re-trigger to stop recording
        if (GlobalStates.regionSelectorOpen) GlobalStates.regionSelectorOpen = false
        GlobalStates.regionSelectorOpen = true
    }

    function longshot() {
        if (longshotSession.active) {
            longshotSession.finish();
            return;
        }
        longshotSession.dismissResult();
        root.action = RegionSelection.SnipAction.LongShot
        root.selectionMode = RegionSelection.SelectionMode.RectCorners
        GlobalStates.regionSelectorOpen = true
    }

    function cancelLongshot() {
        longshotSession.cancel();
        root.dismiss();
    }

    LongShotSession {
        id: longshotSession
    }

    IpcHandler {
        target: "region"

        function screenshot() {
            root.screenshot()
        }
        function search() {
            root.search()
        }
        function ocr() {
            root.ocr()
        }
        function record() {
            root.record()
        }
        function recordWithSound() {
            root.recordWithSound()
        }
        function longshot() {
            root.longshot()
        }
        function pauseLongshot() {
            longshotSession.togglePause()
        }
        function autoLongshot() {
            longshotSession.toggleAutomatic()
        }
        function finishLongshot() {
            longshotSession.finish()
        }
        function cancelLongshot() {
            root.cancelLongshot()
        }
    }

    GlobalShortcut {
        name: "regionScreenshot"
        description: "Takes a screenshot of the selected region"
        onPressed: root.screenshot()
    }
    GlobalShortcut {
        name: "regionLongShot"
        description: "Takes a long screenshot of the selected region"
        onPressed: root.longshot()
    }
    GlobalShortcut {
        name: "regionLongShotPause"
        description: "Pauses or resumes the long screenshot"
        onPressed: longshotSession.togglePause()
    }
    GlobalShortcut {
        name: "regionLongShotCancel"
        description: "Cancels the long screenshot"
        onPressed: root.cancelLongshot()
    }
    GlobalShortcut {
        name: "regionLongShotAuto"
        description: "Switches between manual and automatic long screenshot scrolling"
        onPressed: longshotSession.toggleAutomatic()
    }
    GlobalShortcut {
        name: "regionLongShotInterrupt"
        description: "Pauses automatic scrolling when the user takes control"
        onPressed: longshotSession.interruptAutomatic()
    }
    GlobalShortcut {
        name: "regionSearch"
        description: "Searches the selected region"
        onPressed: root.search()
    }
    GlobalShortcut {
        name: "regionOcr"
        description: "Recognizes text in the selected region"
        onPressed: root.ocr()
    }
    GlobalShortcut {
        name: "regionRecord"
        description: "Records the selected region"
        onPressed: root.record()
    }
    GlobalShortcut {
        name: "regionRecordWithSound"
        description: "Records the selected region with sound"
        onPressed: root.recordWithSound()
    }
}
