pragma ComponentBehavior: Bound
import qs.modules.common.widgets
import qs.services
import QtQuick

// Options toolbar
Toolbar {
    id: root

    // Use a synchronizer on these
    property var action
    property var selectionMode
    // Signals
    signal dismiss()

    ToolbarTabBar {
        objectName: "captureModeTabs"
        visible: root.action === RegionSelection.SnipAction.Copy
            || root.action === RegionSelection.SnipAction.Edit
            || root.action === RegionSelection.SnipAction.LongShot
        tabButtonList: [
            {"icon": "content_cut", "name": Translation.tr("Screenshot")},
            {"icon": "screenshot_monitor", "name": Translation.tr("Long screenshot")}
        ]
        currentIndex: root.action === RegionSelection.SnipAction.LongShot ? 1 : 0
        onActivated: index => {
            if (!visible) return;
            root.action = index === 1 ? RegionSelection.SnipAction.LongShot : RegionSelection.SnipAction.Copy;
            if (index === 1) root.selectionMode = RegionSelection.SelectionMode.RectCorners;
        }
    }

    ToolbarTabBar {
        id: tabBar
        objectName: "selectionShapeTabs"
        visible: root.action !== RegionSelection.SnipAction.LongShot
        tabButtonList: [
            {"icon": "activity_zone", "name": Translation.tr("Rect")},
            {"icon": "gesture", "name": Translation.tr("Circle")}
        ]
        currentIndex: root.selectionMode === RegionSelection.SelectionMode.RectCorners ? 0 : 1
        onActivated: index => {
            root.selectionMode = index === 0 ? RegionSelection.SelectionMode.RectCorners : RegionSelection.SelectionMode.Circle;
        }
    }
}
