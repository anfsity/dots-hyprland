pragma ComponentBehavior: Bound
import qs
import qs.modules.common
import qs.modules.common.functions
import qs.modules.common.widgets
import qs.services
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Qt5Compat.GraphicalEffects
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import Quickshell.Hyprland

// Options toolbar
Toolbar {
    id: root

    // Use a synchronizer on these
    property var action
    property var selectionMode
    // Signals
    signal dismiss()

    ToolbarTabBar {
        visible: root.action === RegionSelection.SnipAction.Copy
            || root.action === RegionSelection.SnipAction.Edit
            || root.action === RegionSelection.SnipAction.LongShot
        tabButtonList: [
            {"icon": "content_cut", "name": Translation.tr("Screenshot")},
            {"icon": "screenshot_monitor", "name": Translation.tr("Long screenshot")}
        ]
        currentIndex: root.action === RegionSelection.SnipAction.LongShot ? 1 : 0
        onCurrentIndexChanged: {
            if (!visible) return;
            root.action = currentIndex === 1 ? RegionSelection.SnipAction.LongShot : RegionSelection.SnipAction.Copy;
            if (currentIndex === 1) root.selectionMode = RegionSelection.SelectionMode.RectCorners;
        }
    }

    ToolbarTabBar {
        id: tabBar
        visible: root.action !== RegionSelection.SnipAction.LongShot
        tabButtonList: [
            {"icon": "activity_zone", "name": Translation.tr("Rect")},
            {"icon": "gesture", "name": Translation.tr("Circle")}
        ]
        currentIndex: root.selectionMode === RegionSelection.SelectionMode.RectCorners ? 0 : 1
        onCurrentIndexChanged: {
            root.selectionMode = currentIndex === 0 ? RegionSelection.SelectionMode.RectCorners : RegionSelection.SelectionMode.Circle;
        }
    }
}
