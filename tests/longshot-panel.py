#!/usr/bin/env python3
"""Exercise the real longshot panel offscreen; optionally retain PNG renders.

Usage: .venv/bin/python tests/longshot-panel.py [--artifacts DIRECTORY]
No desktop capture, mouse injection, clipboard access, or real shell is used.
"""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from PIL import Image, ImageDraw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts', type=Path)
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1] / 'dots/.config/quickshell/ii/modules/ii/regionSelector/LongShotPanel.qml'
    runner = shutil.which('qmltestrunner6') or '/usr/lib/qt6/bin/qmltestrunner'
    with tempfile.TemporaryDirectory(prefix='longshot-panel-test-') as temporary:
        root = Path(temporary)
        artifacts = (args.artifacts or root).resolve()
        artifacts.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, root / source.name)
        shutil.copy2(source.with_name('OptionsToolbar.qml'), root / 'OptionsToolbar.qml')
        # Exercise the actual selector/tab logic; mock only styling, translation
        # and the enum container, without starting a real screen capture.
        config = source.parents[2]
        for module in ('common', 'common/models', 'common/widgets', 'common/functions'):
            directory = root / 'imports/qs/modules' / module
            directory.mkdir(parents=True, exist_ok=True)
            (directory / 'qmldir').write_text('module qs.modules.' + module.replace('/', '.') + '\nDummy 1.0 Dummy.qml\n')
            (directory / 'Dummy.qml').write_text('import QtQml\nQtObject {}')
        common = root / 'imports/qs/modules/common'
        (common / 'qmldir').write_text('module qs.modules.common\nsingleton Appearance 1.0 Appearance.qml\n')
        (common / 'Appearance.qml').write_text('pragma Singleton\nimport QtQuick\nQtObject { property QtObject colors: QtObject { property color colSecondaryContainer: "#445577" }; property QtObject m3colors: QtObject { property color m3surfaceContainer: "#222233" } }')
        models = common / 'models'
        shutil.copy2(config / 'common/models/AnimatedTabIndexPair.qml', models / 'AnimatedTabIndexPair.qml')
        with (models / 'qmldir').open('a') as file:
            file.write('AnimatedTabIndexPair 1.0 AnimatedTabIndexPair.qml\n')
        widgets = common / 'widgets'
        for name in ('Toolbar', 'ToolbarTabBar'):
            shutil.copy2(config / f'common/widgets/{name}.qml', widgets / f'{name}.qml')
        (widgets / 'ToolbarTabButton.qml').write_text('import QtQuick.Controls\nButton { property string materialSymbol; property bool current }')
        (widgets / 'StyledRectangularShadow.qml').write_text('import QtQuick\nItem { property var target }')
        with (widgets / 'qmldir').open('a') as file:
            for name in ('Toolbar', 'ToolbarTabBar', 'ToolbarTabButton', 'StyledRectangularShadow'):
                file.write(f'{name} 1.0 {name}.qml\n')
        services = root / 'imports/qs/services'
        services.mkdir(parents=True)
        (services / 'qmldir').write_text('module qs.services\nsingleton Translation 1.0 Translation.qml\n')
        (services / 'Translation.qml').write_text('pragma Singleton\nimport QtQml\nQtObject { function tr(text) { return text; } }')
        (root / 'RegionSelection.qml').write_text('import QtQuick\nItem { enum SnipAction { Copy, Edit, Search, CharRecognition, Record, RecordWithSound, LongShot } enum SelectionMode { RectCorners, Circle } }')
        preview = Image.new('RGB', (192, 1200), '#f7f8fc')
        draw = ImageDraw.Draw(preview)
        draw.rectangle((0, 0, 192, 64), fill='#253451')
        draw.text((12, 20), 'SCROLL CAPTURE', fill='white')
        for index in range(24):
            y = 90 + index * 44
            draw.text((12, y), f'{index + 1:02d}  Reading notes', fill='#26324d')
            draw.rounded_rectangle((12, y + 19, 175, y + 22), radius=1, fill='#bcc7db')
        preview.save(root / 'preview.png')
        wide_preview = Image.new('RGB', (2441, 713), '#f7f8fc')
        wide_draw = ImageDraw.Draw(wide_preview)
        wide_draw.rectangle((0, 0, 2441, 110), fill='#253451')
        for index in range(8):
            y = 150 + index * 62
            wide_draw.rounded_rectangle((60, y, 1800 - index * 70, y + 12), radius=6, fill='#9aa9c4')
        wide_preview.save(root / 'preview-wide.png')
        text = r'''import QtQuick
import QtTest

TestCase {
    id: testCase
    name: "LongShotPanel"
    when: windowShown
    visible: true
    width: 360
    height: 650
    property var panel
    RegionSelection { id: enumContainer }
    Component { id: factory; LongShotPanel { x: 12; y: 12; width: 332; height: implicitHeight } }
    Component { id: toolbarFactory; OptionsToolbar { y: 470; width: implicitWidth; height: implicitHeight } }
    SignalSpy { id: pauseSpy; signalName: "pauseRequested" }
    SignalSpy { id: finishSpy; signalName: "finishRequested" }
    SignalSpy { id: openSpy; signalName: "openRequested" }
    SignalSpy { id: autoSpy; signalName: "autoRequested" }
    function init() {
        failOnWarning(/.*/);
        panel = createTemporaryObject(factory, testCase, {
            phase: "capturing", frames: 7, imageWidth: 1180,
            imageHeight: 5200, frameHeight: 700, quality: 0.98,
            previewSource: PREVIEW_URL
        });
        verify(panel !== null);
        pauseSpy.target = panel; pauseSpy.clear();
        finishSpy.target = panel; finishSpy.clear();
        openSpy.target = panel; openSpy.clear();
        autoSpy.target = panel; autoSpy.clear();
        tryCompare(findChild(panel, "previewImage"), "status", Image.Ready);
        wait(50);
    }
    function cleanup() {
        pauseSpy.target = null; finishSpy.target = null; openSpy.target = null; autoSpy.target = null;
    }
    function test_capture_controls() {
        const pauseButton = findChild(panel, "pauseButton");
        mouseClick(pauseButton, pauseButton.width / 2, pauseButton.height / 2);
        compare(pauseSpy.count, 1);
        mouseClick(findChild(panel, "finishButton"));
        compare(finishSpy.count, 1);
        panel.phase = "saving";
        compare(findChild(panel, "finishButton").enabled, false);
        compare(findChild(panel, "pauseButton").enabled, false);
    }
    function test_preview_follows_tail_but_can_be_inspected() {
        const flick = findChild(panel, "previewFlick");
        tryVerify(() => flick.contentY > 0);
        panel.followTail = false;
        flick.contentY = 0;
        compare(flick.contentY, 0);
    }
    function test_auto_toggle_controls_and_guidance() {
        const automatic = findChild(panel, "autoButton");
        verify(automatic.visible && automatic.enabled);
        mouseClick(automatic);
        compare(autoSpy.count, 1);
        panel.automatic = true;
        compare(automatic.selected, true);
        verify(findChild(panel, "guidance").text.includes("pause"));
        panel.phase = "paused";
        verify(automatic.enabled);
        panel.phase = "saving";
        verify(!automatic.enabled);
        panel.phase = "capturing";
        panel.autoAvailable = false;
        verify(!automatic.enabled);
        panel.phase = "done";
        verify(!automatic.visible);
    }
    function test_pause_press_keeps_its_intent_if_manual_input_pauses_first() {
        panel.automatic = true;
        const pause = findChild(panel, "pauseButton");
        mousePress(pause);
        panel.phase = "paused";
        mouseRelease(pause);
        compare(pauseSpy.count, 1);
        compare(pauseSpy.signalArguments[0][0], false);
    }
    function test_done_and_error_actions() {
        panel.phase = "done";
        tryCompare(findChild(panel, "finishButton"), "visible", false);
        tryCompare(findChild(panel, "openButton"), "visible", true);
        mouseClick(findChild(panel, "openButton"));
        compare(openSpy.count, 1);
        panel.phase = "error";
        panel.detail = "Select the region again";
        compare(findChild(panel, "guidance").text, panel.detail);
        compare(findChild(panel, "openButton").visible, false);
    }
    function test_compact_has_all_controls_without_the_preview() {
        panel.compact = true;
        compare(findChild(panel, "previewPane").visible, false);
        tryVerify(() => panel.height <= 210);
        verify(findChild(panel, "finishButton").visible);
    }
    function test_short_frame_opaque_surface_data() {
        return [
            {tag: "dark", surface: "#20211f26", preview: "#2017131d", text: "#e7e0ec", muted: "#cac4d0", accent: "#d0bcff", onAccent: "#381e72", warning: "#ffb4ab"},
            {tag: "light", surface: "#20f3edf7", preview: "#20ffffff", text: "#211f26", muted: "#49454f", accent: "#6750a4", onAccent: "#ffffff", warning: "#b3261e"}
        ];
    }
    function test_short_frame_opaque_surface(data) {
        panel.surfaceColor = data.surface;
        panel.surfaceVariant = data.preview;
        panel.textColor = data.text;
        panel.mutedColor = data.muted;
        panel.accentColor = data.accent;
        panel.accentTextColor = data.onAccent;
        panel.warningColor = data.warning;
        panel.phase = "error";
        panel.frames = 1;
        panel.imageWidth = 2441;
        panel.imageHeight = 713;
        panel.previewSource = WIDE_PREVIEW_URL;
        panel.detail = "No overlapping scroll captured; select scrolling content and scroll down slowly";
        tryCompare(findChild(panel, "previewImage"), "status", Image.Ready);
        wait(250);
        const preview = findChild(panel, "previewPane");
        verify(preview.height <= 130, "Short frames should not leave a tall empty preview");
        compare(panel.color.a, 1);
        compare(preview.color.a, 1);
        const rendered = grabImage(panel);
        compare(rendered.alpha(panel.width / 2, panel.height - 8), 255);
        compare(rendered.pixel(panel.width / 2, panel.height - 8), Qt.alpha(data.surface, 1));
        verify(!findChild(panel, "guidance").truncated);
        rendered.save(ARTIFACT_DIRECTORY + "/longshot-error-" + data.tag + ".png");
    }
    function test_selector_mode_changes_do_not_form_a_binding_loop() {
        const toolbar = createTemporaryObject(toolbarFactory, testCase, {
            action: RegionSelection.SnipAction.LongShot,
            selectionMode: RegionSelection.SelectionMode.RectCorners
        });
        verify(toolbar !== null);
        wait(30);
        compare(toolbar.action, RegionSelection.SnipAction.LongShot);
        const modes = findChild(toolbar, "captureModeTabs");
        const shapes = findChild(toolbar, "selectionShapeTabs");
        compare(modes.currentIndex, 1);
        modes.setCurrentIndex(0);
        compare(toolbar.action, RegionSelection.SnipAction.Copy);
        shapes.setCurrentIndex(1);
        compare(toolbar.selectionMode, RegionSelection.SelectionMode.Circle);
        modes.setCurrentIndex(1);
        compare(toolbar.action, RegionSelection.SnipAction.LongShot);
        compare(toolbar.selectionMode, RegionSelection.SelectionMode.RectCorners);
        compare(shapes.currentIndex, 0);
    }
    function test_recovery_guidance_and_render() {
        panel.captureStatus = "ambiguous";
        verify(findChild(panel, "guidance").text.includes("Repeated"));
        panel.captureStatus = "backtracking";
        verify(findChild(panel, "guidance").text.includes("last captured"));
        panel.captureStatus = "capturing";
        panel.tr = function(text) { return TRANSLATIONS[text] ?? text; };
        verify(panel.height <= 550);
        wait(250);
        let saved = false;
        verify(panel.grabToImage(result => { saved = result.saveToFile(RENDER_PATH); }));
        tryVerify(() => saved);
        panel.automatic = true;
        wait(100);
        grabImage(panel).save(ARTIFACT_DIRECTORY + "/longshot-auto.png");
    }
}'''
        translations = {'Long screenshot': '长截图', 'Capturing': '采集中', 'Pause': '暂停',
                        'Finish': '完成', '%1 frames': '%1 帧', 'Auto': '自动',
                        'Auto scrolling': '自动滚动中',
                        'Auto-scroll is on. Move the pointer or scroll manually to pause.': '正在自动滚动，移动鼠标或手动滚轮可暂停。',
                        'Scroll slowly. Press Super+Shift+S to finish.': '缓慢向下滚动，按 Super+Shift+S 完成。'}
        text = text.replace('WIDE_PREVIEW_URL', json.dumps((root / 'preview-wide.png').as_uri()))
        text = text.replace('PREVIEW_URL', json.dumps((root / 'preview.png').as_uri()))
        text = text.replace('ARTIFACT_DIRECTORY', json.dumps(str(artifacts)))
        text = text.replace('TRANSLATIONS', '(' + json.dumps(translations, ensure_ascii=False) + ')')
        text = text.replace('RENDER_PATH', json.dumps(str(artifacts / 'longshot-panel.png')))
        (root / 'tst_panel.qml').write_text(text)
        env = dict(os.environ, QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software',
                   QT_QUICK_CONTROLS_STYLE='Basic', QT_QPA_PLATFORMTHEME='', QT_IM_MODULE='')
        return subprocess.run([runner, '-input', str(root), '-import', str(root / 'imports')], env=env).returncode


if __name__ == '__main__':
    raise SystemExit(main())
