# vim: ft=python fileencoding=utf-8 sts=4 sw=4 et:

# Copyright 2016-2021 Florian Bruhin (The Compiler) <mail@qutebrowser.org>
#
# This file is part of qutebrowser.
#
# qutebrowser is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# qutebrowser is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with qutebrowser.  If not, see <https://www.gnu.org/licenses/>.

import pytest

from PyQt5.QtCore import Qt, QObject, pyqtSignal, QTimer, QEvent
from PyQt5.QtGui import QKeySequence

from qutebrowser.utils import usertypes, objreg
from qutebrowser.keyinput import keyutils, basekeyparser
from qutebrowser.misc import objects


class FakeKeyparser(QObject):

    """A fake BaseKeyParser which doesn't handle anything."""

    keystring_updated = pyqtSignal(str)
    request_leave = pyqtSignal(usertypes.KeyMode, str, bool)
    forward_partial_key = pyqtSignal(str)
    clear_partial_keys = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.passthrough = False
        self.allow_partial_timeout = False
        self.allow_forward = True
        self.forward_widget_name = None

    def handle(self, evt, *, dry_run=False):
        return QKeySequence.NoMatch


@pytest.fixture
def modeman(mode_manager):
    mode_manager.register(usertypes.KeyMode.normal, FakeKeyparser())
    return mode_manager


@pytest.fixture(autouse=True)
def set_qapp(monkeypatch, qapp):
    monkeypatch.setattr(objects, 'qapp', qapp)


@pytest.mark.parametrize('key, modifiers, filtered', [
    (Qt.Key_A, Qt.NoModifier, True),
    (Qt.Key_Up, Qt.NoModifier, False),
    # https://github.com/qutebrowser/qutebrowser/issues/1207
    (Qt.Key_A, Qt.ShiftModifier, True),
    (Qt.Key_A, Qt.ShiftModifier | Qt.ControlModifier, False),
])
def test_non_alphanumeric(key, modifiers, filtered, modeman):
    """Make sure non-alphanumeric keys are passed through correctly."""
    evt = keyutils.KeyInfo(key=key, modifiers=modifiers).to_event()
    assert modeman.handle_event(evt) == filtered


class FakeKeyparserWithTimeout(QObject):

    """A minimal fake BaseKeyParser for testing partial timeouts."""

    keystring_updated = pyqtSignal(str)
    request_leave = pyqtSignal(usertypes.KeyMode, str, bool)
    forward_partial_key = pyqtSignal(str)
    clear_partial_keys = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.passthrough = False
        self.allow_partial_timeout = True
        self.allow_forward = True
        self.forward_widget_name = None
        self.fake_clear_keystring_called = False

    def handle(self, evt, *, dry_run=False):
        txt = str(keyutils.KeyInfo.from_event(evt))
        if 'a' == txt:
            return QKeySequence.ExactMatch
        elif 'b' == txt:
            return QKeySequence.PartialMatch
        else:
            return QKeySequence.NoMatch

    def clear_keystring(self):
        self.fake_clear_keystring_called = True
        self.keystring_updated.emit('')


@pytest.fixture
def modeman_with_timeout(mode_manager):
    mode_manager.register(usertypes.KeyMode.normal, FakeKeyparserWithTimeout())
    return mode_manager


@pytest.mark.parametrize('data_sequence', [
    ((Qt.Key_A, 'timer_inactive'),),
    ((Qt.Key_B, 'timer_active'),),
    ((Qt.Key_C, 'timer_inactive'),),
    ((Qt.Key_B, 'timer_active'), (Qt.Key_A, 'timer_inactive'),),
    ((Qt.Key_B, 'timer_active'), (Qt.Key_B, 'timer_reset'),),
    ((Qt.Key_B, 'timer_active'), (Qt.Key_C, 'timer_inactive'),),
    ((Qt.Key_B, 'timer_active'), (Qt.Key_B, 'timer_reset'), (Qt.Key_A,
        'timer_inactive'),),
    ((Qt.Key_B, 'timer_active'), (Qt.Key_B, 'timer_reset'), (Qt.Key_B,
        'timer_reset'),),
    ((Qt.Key_B, 'timer_active'), (Qt.Key_B, 'timer_reset'), (Qt.Key_C,
        'timer_inactive'),),
])
def test_partial_keychain_timeout(modeman_with_timeout, config_stub, qtbot, data_sequence):
    """Test partial keychain timeout behavior."""
    mode = modeman_with_timeout.mode
    timeout = 100
    config_stub.val.input.partial_timeout = timeout
    timer = modeman_with_timeout._partial_timer
    parser = modeman_with_timeout.parsers[mode]
    assert not timer.isActive()

    behavior = None
    for key, behavior in data_sequence:
        keyinfo = keyutils.KeyInfo(key, Qt.NoModifier)
        if behavior == 'timer_active':
            # Timer should be active
            modeman_with_timeout.handle_event(keyinfo.to_event())
            assert timer.isSingleShot()
            assert timer.interval() == timeout
            assert timer.isActive()
        elif behavior == 'timer_inactive':
            # Timer should be inactive
            modeman_with_timeout.handle_event(keyinfo.to_event())
            assert not timer.isActive()
            assert not parser.fake_clear_keystring_called
        elif behavior == 'timer_reset':
            # Timer should be reset after handling the key
            half_timer = QTimer()
            half_timer.setSingleShot(True)
            half_timer.setInterval(timeout//2)
            half_timer.start()
            # Simulate a half timeout to check for reset
            qtbot.wait_signal(half_timer.timeout).wait()
            assert (timeout - (timeout//4)) > timer.remainingTime()
            modeman_with_timeout.handle_event(keyinfo.to_event())
            assert (timeout - (timeout//4)) < timer.remainingTime()
            assert timer.isActive()
        else:
            pytest.fail('Unreachable')
    if behavior in ['timer_active', 'timer_reset']:
        # Now simulate a timeout and check the keystring has been cleared.
        with qtbot.wait_signal(modeman_with_timeout.keystring_updated) as blocker:
            timer.timeout.emit()
        assert parser.fake_clear_keystring_called
        parser.fake_clear_keystring_called = False
        assert blocker.args == [mode, '']


class FakeEventFilter(QObject):
    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        return True


@pytest.fixture
def modeman_with_basekeyparser(mode_manager, config_stub):
    fake_event_filter = FakeEventFilter()
    objreg.register('fake-event-filter', fake_event_filter, scope='window',
        window=0)
    config_stub.val.bindings.default = {}
    config_stub.val.bindings.commands = {
        'normal': {
            'bb': 'message-info bb',
            'byy': 'message-info byy',
        }
    }
    config_stub.val.bindings.key_mappings = {}
    mode = usertypes.KeyMode.normal
    mode_manager.register(mode,
        basekeyparser.BaseKeyParser(mode=mode,
                                    win_id=0,
                                    passthrough=True,
                                    forward_widget_name='fake-event-filter'))
    yield mode_manager
    objreg.delete('fake-event-filter', scope='window', window=0)


def test_release_forwarding(modeman_with_basekeyparser):
    def helper_data(res, mwb):
        return res, len(mwb._partial_match_events), \
            len(mwb._releaseevents_to_pass)
    mwb = modeman_with_basekeyparser

    info_b = keyutils.KeyInfo(Qt.Key_B, Qt.NoModifier)
    info_c = keyutils.KeyInfo(Qt.Key_C, Qt.NoModifier)

    res = mwb.handle_event(info_b.to_event(QEvent.KeyPress))
    assert (True, 1, 0) == helper_data(res, mwb)
    assert not mwb._partial_match_events[0].is_released()
    res = mwb.handle_event(info_c.to_event(QEvent.KeyPress))
    assert (True, 0, 2) == helper_data(res, mwb)
    res = mwb.handle_event(info_b.to_event(QEvent.KeyRelease))
    assert (False, 0, 1) == helper_data(res, mwb)
    res = mwb.handle_event(info_c.to_event(QEvent.KeyRelease))
    assert (False, 0, 0) == helper_data(res, mwb)

    info_y = keyutils.KeyInfo(Qt.Key_Y, Qt.NoModifier)

    res = mwb.handle_event(info_b.to_event(QEvent.KeyPress))
    assert (True, 1, 0) == helper_data(res, mwb)
    assert not mwb._partial_match_events[0].is_released()
    res = mwb.handle_event(info_y.to_event(QEvent.KeyPress))
    assert (True, 2, 0) == helper_data(res, mwb)
    assert not mwb._partial_match_events[0].is_released()
    assert not mwb._partial_match_events[1].is_released()
    res = mwb.handle_event(info_y.to_event(QEvent.KeyRelease))
    assert (True, 2, 0) == helper_data(res, mwb)
    assert not mwb._partial_match_events[0].is_released()
    assert mwb._partial_match_events[1].is_released()
    res = mwb.handle_event(info_c.to_event(QEvent.KeyPress))
    assert (True, 0, 2) == helper_data(res, mwb)
    res = mwb.handle_event(info_c.to_event(QEvent.KeyRelease))
    assert (False, 0, 1) == helper_data(res, mwb)
    res = mwb.handle_event(info_b.to_event(QEvent.KeyRelease))
    assert (False, 0, 0) == helper_data(res, mwb)

    res = mwb.handle_event(info_b.to_event(QEvent.KeyPress))
    assert (True, 1, 0) == helper_data(res, mwb)
    assert not mwb._partial_match_events[0].is_released()
    res = mwb.handle_event(info_c.to_event(QEvent.KeyRelease))
    assert (True, 1, 0) == helper_data(res, mwb)
