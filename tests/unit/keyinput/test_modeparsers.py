# vim: ft=python fileencoding=utf-8 sts=4 sw=4 et:

# Copyright 2015-2021 Florian Bruhin (The Compiler) <mail@qutebrowser.org>:
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

"""Tests for mode parsers."""

from unittest import mock

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QKeySequence

import pytest

from qutebrowser.keyinput import modeparsers, keyutils


@pytest.fixture
def commandrunner(stubs):
    return stubs.FakeCommandRunner()


@pytest.fixture
def handle_text():
    """Helper function to handle multiple fake keypresses."""
    def func(kp, *args):
        for key in args:
            info = keyutils.KeyInfo(key, Qt.NoModifier)
            kp.handle(info.to_event())
    return func


class TestsNormalKeyParser:

    @pytest.fixture(autouse=True)
    def patch_stuff(self, monkeypatch, stubs, keyinput_bindings):
        """Set up mocks and read the test config."""
        monkeypatch.setattr(
            'qutebrowser.keyinput.basekeyparser.usertypes.Timer',
            stubs.FakeTimer)

    @pytest.fixture
    def keyparser(self, commandrunner):
        kp = modeparsers.NormalKeyParser(win_id=0, commandrunner=commandrunner)
        return kp

    def test_keychain(self, keyparser, commandrunner):
        """Test valid keychain."""
        # Press 'z' which is ignored because of no match
        # Then start the real chain
        chain = keyutils.KeySequence.parse('zba')
        for info in chain:
            keyparser.handle(info.to_event())
        assert commandrunner.commands == [('message-info ba', None)]
        assert not keyparser._sequence


class TestHintKeyParser:

    @pytest.fixture
    def hintmanager(self, stubs):
        return stubs.FakeHintManager()

    @pytest.fixture
    def keyparser(self, config_stub, key_config_stub, commandrunner,
                  hintmanager):
        return modeparsers.HintKeyParser(win_id=0,
                                         hintmanager=hintmanager,
                                         commandrunner=commandrunner)

    @pytest.mark.parametrize('bindings, keychain, prefix, hint', [
        (
            ['aa', 'as'],
            'as',
            'a',
            'as'
        ),
        (
            ['21', '22'],
            '<Num+2><Num+2>',
            '2',
            '22'
        ),
        (
            ['äa', 'äs'],
            'äs',
            'ä',
            'äs'
        ),
        (
            ['не', 'на'],
            'не',
            '<Н>',
            'не',
        ),
    ])
    def test_match(self, keyparser, hintmanager,
                   bindings, keychain, prefix, hint):
        keyparser.update_bindings(bindings)

        seq = keyutils.KeySequence.parse(keychain)
        assert len(seq) == 2

        match = keyparser.handle(seq[0].to_event())
        assert match == QKeySequence.PartialMatch
        assert hintmanager.keystr == prefix

        match = keyparser.handle(seq[1].to_event())
        assert match == QKeySequence.ExactMatch
        assert hintmanager.keystr == hint

    def test_match_key_mappings(self, config_stub, keyparser, hintmanager):
        config_stub.val.bindings.key_mappings = {'α': 'a', 'σ': 's'}
        keyparser.update_bindings(['aa', 'as'])

        seq = keyutils.KeySequence.parse('ασ')
        assert len(seq) == 2

        match = keyparser.handle(seq[0].to_event())
        assert match == QKeySequence.PartialMatch
        assert hintmanager.keystr == 'a'

        match = keyparser.handle(seq[1].to_event())
        assert match == QKeySequence.ExactMatch
        assert hintmanager.keystr == 'as'

    def test_command(self, keyparser, config_stub, hintmanager, commandrunner):
        config_stub.val.bindings.commands = {
            'hint': {'abc': 'message-info abc'}
        }

        keyparser.update_bindings(['xabcy'])

        steps = [
            (Qt.Key_X, QKeySequence.PartialMatch, 'x'),
            (Qt.Key_A, QKeySequence.PartialMatch, 'x'),
            (Qt.Key_B, QKeySequence.PartialMatch, 'x'),
            (Qt.Key_C, QKeySequence.ExactMatch, ''),
        ]
        for key, expected_match, keystr in steps:
            info = keyutils.KeyInfo(key, Qt.NoModifier)
            match = keyparser.handle(info.to_event())
            assert match == expected_match
            assert hintmanager.keystr == keystr
            if key != Qt.Key_C:
                assert not commandrunner.commands

        assert commandrunner.commands == [('message-info abc', None)]

    @pytest.mark.parametrize('seq, hint_seq', [
        ((Qt.Key_F,), None),
        ((Qt.Key_F,), 'f'),
        ((Qt.Key_F,), 'fz'),
        ((Qt.Key_F,), 'fzz'),
        ((Qt.Key_F,), 'fza'),
        ((Qt.Key_F, Qt.Key_G), None),
        ((Qt.Key_F, Qt.Key_G), 'f'),
        ((Qt.Key_F, Qt.Key_G), 'fg'),
        ((Qt.Key_F, Qt.Key_G), 'fgz'),
        ((Qt.Key_F, Qt.Key_G), 'fgzz'),
        ((Qt.Key_F, Qt.Key_G), 'fgza'),
        ((Qt.Key_F, Qt.Key_G, Qt.Key_H), None),
        ((Qt.Key_F, Qt.Key_G, Qt.Key_H), 'f'),
        ((Qt.Key_F, Qt.Key_G, Qt.Key_H), 'fg'),
        ((Qt.Key_F, Qt.Key_G, Qt.Key_H), 'fgh'),
        ((Qt.Key_F, Qt.Key_G, Qt.Key_H), 'fghz'),
        ((Qt.Key_F, Qt.Key_G, Qt.Key_H), 'fghzz'),
        ((Qt.Key_F, Qt.Key_G, Qt.Key_H), 'fghza'),
    ])
    def test_forward_keys(self, config_stub, handle_text, keyparser, qtbot,
                          hintmanager, commandrunner, seq, hint_seq):
        command_parser = keyparser._command_parser
        config_stub.val.bindings.commands = {
            'hint': {
                'fy': 'message-info fy',
                'fgy': 'message-info fgy',
                'fghy': 'message-info fghy',
            }
        }
        if hint_seq is not None:
            keyparser.update_bindings([hint_seq, 'zz'])
        forward_partial_key = mock.Mock()
        command_parser.forward_partial_key.connect(forward_partial_key)
        handle_text(keyparser, *seq)
        assert not commandrunner.commands
        seq = list(seq) + [Qt.Key_Z]
        signals = [command_parser.forward_partial_key] * len(seq)
        with qtbot.wait_signals(signals) as blocker:
            handle_text(keyparser, seq[-1])
        assert forward_partial_key.call_args_list == [
            ((str(keyutils.KeyInfo(key, Qt.NoModifier)),),) for key in seq
        ]
        if hint_seq is not None:
            if len(seq) > len(hint_seq):
                assert hintmanager.keystr == 'z'
            else:
                assert hintmanager.keystr == hint_seq[:len(seq)]
        else:
            assert hintmanager.keystr == ''

    @pytest.mark.parametrize('seq, hint_seq, keystr', [
        ((Qt.Key_F,), None, None),
        ((Qt.Key_F,), 'f', None),
        ((Qt.Key_F,), 'fz', None),
        ((Qt.Key_F,), 'fzz', None),
        ((Qt.Key_F,), 'fza', None),
        ((Qt.Key_F, Qt.Key_G), None, None),
        ((Qt.Key_F, Qt.Key_G), 'f', 'g'),
        ((Qt.Key_F, Qt.Key_G), 'fg', None),
        ((Qt.Key_F, Qt.Key_G), 'fgz', None),
        ((Qt.Key_F, Qt.Key_G), 'fgzz', None),
        ((Qt.Key_F, Qt.Key_G), 'fgza', None),
        ((Qt.Key_F, Qt.Key_G, Qt.Key_H), None, None),
        ((Qt.Key_F, Qt.Key_G, Qt.Key_H), 'f', 'gh'),
        ((Qt.Key_F, Qt.Key_G, Qt.Key_H), 'fg', 'h'),
        ((Qt.Key_F, Qt.Key_G, Qt.Key_H), 'fgh', None),
        ((Qt.Key_F, Qt.Key_G, Qt.Key_H), 'fghz', None),
        ((Qt.Key_F, Qt.Key_G, Qt.Key_H), 'fghzz', None),
        ((Qt.Key_F, Qt.Key_G, Qt.Key_H), 'fghza', None),
    ])
    def test_forward_keys_partial(self, config_stub, handle_text, keyparser,
                                  qtbot, hintmanager, commandrunner, seq,
                                  hint_seq, keystr):
        command_parser = keyparser._command_parser
        config_stub.val.bindings.commands = {
            'hint': {
                'fy': 'message-info fy',
                'fgy': 'message-info fgy',
                'fghy': 'message-info fghy',
            }
        }
        if hint_seq is not None:
            keyparser.update_bindings([hint_seq, 'gh', 'h'])
        forward_partial_key = mock.Mock()
        command_parser.forward_partial_key.connect(forward_partial_key)
        handle_text(keyparser, *seq)
        assert not commandrunner.commands
        signals = [command_parser.forward_partial_key] * len(seq)
        with qtbot.wait_signals(signals) as blocker:
            handle_text(keyparser, Qt.Key_F)
        assert forward_partial_key.call_args_list == [
            ((str(keyutils.KeyInfo(key, Qt.NoModifier)),),) for key in seq
        ]
        assert command_parser._sequence == keyutils.KeySequence.parse('f')
        if hint_seq is not None:
            if keystr is not None:
                assert len(seq) > len(hint_seq)
                assert hintmanager.keystr == keystr
            else:
                assert hintmanager.keystr == hint_seq[:len(seq)]
        else:
            assert hintmanager.keystr == ''.join(
                    str(keyutils.KeyInfo(key, Qt.NoModifier)) for key in seq)

    @pytest.mark.parametrize('data_sequence', [
        ((Qt.Key_A, 'timer_inactive'),),
        ((Qt.Key_B, 'timer_active'),),
        ((Qt.Key_C, 'timer_inactive'),),
        ((Qt.Key_B, 'timer_active'), (Qt.Key_A, 'timer_inactive'),),
        ((Qt.Key_B, 'timer_active'), (Qt.Key_B, 'timer_reset'),),
        ((Qt.Key_B, 'timer_active'), (Qt.Key_C, 'timer_inactive'),),
        ((Qt.Key_B, 'timer_active'), (Qt.Key_B, 'timer_reset'), (Qt.Key_A, 'timer_inactive'),),
        ((Qt.Key_B, 'timer_active'), (Qt.Key_B, 'timer_reset'), (Qt.Key_B, 'timer_reset'),),
        ((Qt.Key_B, 'timer_active'), (Qt.Key_B, 'timer_reset'), (Qt.Key_C, 'timer_inactive'),),
    ])
    def test_partial_keychain_timeout(self, keyparser, config_stub, qtbot,
                                      hintmanager, commandrunner,
                                      data_sequence):
        """Test partial keychain timeout behavior."""
        command_parser = keyparser._command_parser
        config_stub.val.bindings.commands = {
            'hint': {
                'a': 'message-info a',
                'ba': 'message-info ba',
                'bba': 'message-info bba',
                'bbba': 'message-info bbba',
            }
        }
        keyparser.update_bindings(['bbb'])

        timeout = 100
        config_stub.val.input.partial_timeout = timeout
        timer = keyparser._partial_timer
        assert not timer.isActive()

        for key, behavior in data_sequence:
            keyinfo = keyutils.KeyInfo(key, Qt.NoModifier)
            if behavior == 'timer_active':
                # Timer should be active
                keyparser.handle(keyinfo.to_event())
                assert timer.isSingleShot()
                assert timer.interval() == timeout
                assert timer.isActive()
            elif behavior == 'timer_inactive':
                # Timer should be inactive
                keyparser.handle(keyinfo.to_event())
                assert not timer.isActive()
            elif behavior == 'timer_reset':
                # Timer should be reset after handling the key
                half_timer = QTimer()
                half_timer.setSingleShot(True)
                half_timer.setInterval(timeout//2)
                half_timer.start()
                # Simulate a half timeout to check for reset
                qtbot.wait_signal(half_timer.timeout).wait()
                assert (timeout - (timeout//4)) > timer.remainingTime()
                keyparser.handle(keyinfo.to_event())
                assert (timeout - (timeout//4)) < timer.remainingTime()
                assert timer.isActive()
            else:
                # Unreachable
                assert False
        if behavior in ['timer_active', 'timer_reset']:
            # Now simulate a timeout and check the keystring has been forwarded.
            with qtbot.wait_signal(command_parser.keystring_updated) as blocker:
                timer.timeout.emit()
            assert blocker.args == ['']
            assert hintmanager.keystr == ('b' * len(data_sequence))
