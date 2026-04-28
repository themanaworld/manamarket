"""Tests for utils.parse_mail_cmdargs and utils.TraderState.

parse_mail_cmdargs has subtle quoting behavior that callers (process_whisper)
guard against by checking for empty strings — these tests pin the current
contract so future cleanup doesn't silently change it.

TraderState was ported from mutex.mutex() to threading.Lock(); reset() must
remain idempotent (mutex.unlock() was, threading.Lock.release() is not).
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import utils


class ParseMailCmdArgsTests(unittest.TestCase):
    def test_unquoted_nick_with_message(self):
        self.assertEqual(utils.parse_mail_cmdargs("Bjorn hello"), ("Bjorn", "hello"))

    def test_unquoted_with_multi_word_message(self):
        self.assertEqual(
            utils.parse_mail_cmdargs("Bjorn hello there"),
            ("Bjorn", "hello there"),
        )

    def test_quoted_nick_with_spaces(self):
        self.assertEqual(
            utils.parse_mail_cmdargs('"Some User" hello'),
            ("Some User", "hello"),
        )

    def test_quoted_with_multi_word_message(self):
        self.assertEqual(
            utils.parse_mail_cmdargs('"Some User" hello world'),
            ("Some User", "hello world"),
        )

    def test_too_short_returns_empties(self):
        self.assertEqual(utils.parse_mail_cmdargs(""), ("", ""))
        self.assertEqual(utils.parse_mail_cmdargs("a"), ("", ""))
        self.assertEqual(utils.parse_mail_cmdargs("ab"), ("", ""))

    def test_unterminated_quote_returns_empties(self):
        """Caller treats this as a syntax error via the empty-string guard."""
        self.assertEqual(utils.parse_mail_cmdargs('"Bjorn'), ("", ""))


class TraderStateLockTests(unittest.TestCase):
    def test_initial_state_unlocked(self):
        ts = utils.TraderState()
        self.assertFalse(ts.Trading.locked())
        self.assertEqual(ts.item, 0)
        self.assertEqual(ts.money, 0)
        self.assertEqual(ts.complete, 0)
        self.assertEqual(ts.timer, 0)

    def test_acquire_marks_locked(self):
        ts = utils.TraderState()
        self.assertTrue(ts.Trading.acquire(False))
        self.assertTrue(ts.Trading.locked())

    def test_second_acquire_returns_false(self):
        ts = utils.TraderState()
        ts.Trading.acquire(False)
        self.assertFalse(ts.Trading.acquire(False))

    def test_reset_releases_lock(self):
        ts = utils.TraderState()
        ts.Trading.acquire(False)
        ts.reset()
        self.assertFalse(ts.Trading.locked())

    def test_reset_is_idempotent_when_unlocked(self):
        """mutex.unlock() didn't raise; threading.Lock.release() does. The
        guard in reset() must keep the original idempotent contract."""
        ts = utils.TraderState()
        ts.reset()  # lock was never acquired
        ts.reset()  # called twice in a row

    def test_reset_clears_all_state(self):
        ts = utils.TraderState()
        ts.item = "something"
        ts.money = 12345
        ts.complete = 1
        ts.timer = 999.0
        ts.Trading.acquire(False)
        ts.reset()
        self.assertEqual(ts.item, 0)
        self.assertEqual(ts.money, 0)
        self.assertEqual(ts.complete, 0)
        self.assertEqual(ts.timer, 0)
        self.assertFalse(ts.Trading.locked())


if __name__ == "__main__":
    unittest.main()
