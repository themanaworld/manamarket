"""Characterization tests for main.process_whisper command routing.

process_whisper is the bot's whisper command dispatcher. It pulls in a
lot of module globals, so we import main against a minimal on-disk data
fixture with config / irc / sdnotify stubbed out (the CI image has no
external deps and no config.py). Each test drives one whisper and
asserts the exact sequence of reply strings, which pins the per-command
arity / digit / permission precedence the dispatcher implements.
"""

import os
import sys
import types
import shutil
import tempfile
import unittest

_ORIG_CWD = os.getcwd()
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FIX = tempfile.mkdtemp(prefix="mm_pw_")


def _write_fixture():
    data = os.path.join(_FIX, "data")
    os.makedirs(os.path.join(data, "logs"))
    with open(os.path.join(data, "items.xml"), "w") as f:
        f.write('<items>\n'
                '  <item id="640" type="generic" name="Iron Ore" weight="2" description="ore"/>\n'
                '  <item id="535" type="usable" name="Cherry Cake" weight="1" description="cake"/>\n'
                '</items>\n')
    with open(os.path.join(data, "user.xml"), "w") as f:
        f.write("<users/>\n")
    with open(os.path.join(data, "sale.xml"), "w") as f:
        f.write("<items/>\n")
    open(os.path.join(data, "logs", "sale.log"), "w").close()


def _install_stubs():
    cfg = types.ModuleType("config")
    cfg.irc_enabled = False
    cfg.admin = "admin"
    cfg.relist_time = 604800
    cfg.nosell = []
    cfg.sqlite3_dbfile = "data/mm.db"
    cfg.account = ""; cfg.password = ""; cfg.server = "x"; cfg.port = 0
    cfg.character = 0; cfg.online_interval = 20
    for n in ("irc_server", "irc_channel", "irc_nick", "irc_user",
              "irc_realname", "irc_password"):
        setattr(cfg, n, "x")
    cfg.irc_port = 6667
    sys.modules["config"] = cfg

    irc = types.ModuleType("irc")
    ircc = types.ModuleType("irc.client")
    ircc.Reactor = type("Reactor", (), {})
    ircc.ServerConnectionError = Exception
    ircc.is_channel = lambda c: True
    irc.client = ircc
    sys.modules["irc"] = irc
    sys.modules["irc.client"] = ircc

    sd = types.ModuleType("sdnotify")
    sd.SystemdNotifier = type("SystemdNotifier", (), {"notify": lambda self, *a, **k: None})
    sys.modules["sdnotify"] = sd


_write_fixture()
_install_stubs()
os.chdir(_FIX)
sys.path.insert(0, _REPO)
import main  # noqa: E402
os.chdir(_ORIG_CWD)


def tearDownModule():
    os.chdir(_ORIG_CWD)
    shutil.rmtree(_FIX, ignore_errors=True)


class _Serv:
    def __init__(self):
        self.msgs = []

    def sendall(self, payload):
        # whisper() is patched to return ("W", nick, message); anything
        # else (raw packets) is recorded verbatim so we'd notice it.
        if isinstance(payload, tuple) and payload[:1] == ("W",):
            self.msgs.append(payload[2])
        else:
            self.msgs.append(payload)


class ProcessWhisperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        main.whisper = lambda nick, message: ("W", nick, message)
        main.tradey.saveData = lambda *a, **k: None

    def setUp(self):
        os.chdir(_FIX)
        self.addCleanup(os.chdir, _ORIG_CWD)
        # Empty the user and sale trees, then seed known users.
        for tree in (main.user_tree.root, main.sale_tree.root):
            for elem in list(tree):
                tree.remove(elem)
        main.sale_tree.u_id = set()
        main.user_tree.add_user("seller", 5, 5)
        main.user_tree.add_user("mod", 5, 10)
        main.user_tree.add_user("admin", 5, 20)
        main.trader_state.reset()
        main.trading_enabled = True

    def run_cmd(self, nick, text):
        serv = _Serv()
        main.process_whisper(nick, text, serv)
        return serv.msgs

    # ---- !buy: always "Syntax incorrect" on any arity/digit failure ----
    def test_buy_arity_low(self):
        self.assertEqual(self.run_cmd("seller", "!buy 1"), ["Syntax incorrect."])

    def test_buy_non_digit(self):
        self.assertEqual(self.run_cmd("seller", "!buy a b"), ["Syntax incorrect."])

    def test_buy_arity_high(self):
        self.assertEqual(self.run_cmd("seller", "!buy 1 2 3"), ["Syntax incorrect."])

    def test_buy_uid_not_found(self):
        self.assertEqual(self.run_cmd("seller", "!buy 1 999"),
                         ["Item not found.  Please check the uid number and try again."])

    # ---- !buyitem: len!=4 -> syntax; len==4 non-digit -> silent ----
    def test_buyitem_arity(self):
        self.assertEqual(self.run_cmd("seller", "!buyitem 1 2"), ["Syntax incorrect"])

    def test_buyitem_len4_non_digit_is_silent(self):
        self.assertEqual(self.run_cmd("seller", "!buyitem a b c"), [])

    def test_buyitem_not_found(self):
        self.assertEqual(self.run_cmd("seller", "!buyitem 999 1 1"),
                         ["Item not found. Please check and try again."])

    # ---- !find ----
    def test_find_arity(self):
        self.assertEqual(self.run_cmd("seller", "!find"), ["Syntax incorrect."])

    def test_find_by_id_not_found(self):
        self.assertEqual(self.run_cmd("seller", "!find 640"), ["Item not found."])

    def test_find_by_name_not_found(self):
        self.assertEqual(self.run_cmd("seller", "!find Iron Ore"), ["Item not found."])

    # ---- !identify: user==-10 -> perms; then arity; then accesslevel<10 ----
    def test_identify_unknown_user(self):
        self.assertEqual(self.run_cmd("noone", "!identify 1"),
                         ["You don't have the correct permissions."])

    def test_identify_low_access_no_args(self):
        # Registry normalization: the access gate now fires before the
        # handler, so a sub-level-10 user is denied regardless of arity.
        # (The match version checked arity first and returned "Syntax
        # incorrect." here.)
        self.assertEqual(self.run_cmd("seller", "!identify"),
                         ["You don't have the correct permissions."])

    def test_identify_low_access(self):
        self.assertEqual(self.run_cmd("seller", "!identify 1"),
                         ["You don't have the correct permissions."])

    def test_identify_admin_not_found(self):
        self.assertEqual(self.run_cmd("admin", "!identify 999"),
                         ["Item not found. Please check the uid number and try again."])

    # ---- !setslots: the access gate denies sub-admins uniformly ----
    def test_setslots_unknown_user_denied(self):
        # Registry normalization: an unregistered user now hits the access
        # gate ("permissions") instead of falling through to the
        # unknown-command hint, since !setslots is registered with access=20.
        self.assertEqual(self.run_cmd("noone", "!setslots 5 bob"),
                         ["You don't have the correct permissions."])

    def test_setslots_permission_before_arity(self):
        # seller with too-few args still gets permission error, not syntax.
        self.assertEqual(self.run_cmd("seller", "!setslots 5"),
                         ["You don't have the correct permissions."])

    def test_setslots_admin_arity(self):
        self.assertEqual(self.run_cmd("admin", "!setslots 5"), ["Syntax incorrect."])

    def test_setslots_admin_non_digit(self):
        self.assertEqual(self.run_cmd("admin", "!setslots ab bob"), ["Syntax incorrect."])

    def test_setslots_admin_user_not_found(self):
        self.assertEqual(self.run_cmd("admin", "!setslots 5 ghost"),
                         ["User not found, check and try again."])

    # ---- !setaccess: negative levels accepted ----
    def test_setaccess_admin_non_digit(self):
        self.assertEqual(self.run_cmd("admin", "!setaccess x bob"), ["Syntax incorrect."])

    def test_setaccess_admin_negative_user_not_found(self):
        self.assertEqual(self.run_cmd("admin", "!setaccess -1 ghost"),
                         ["User not found, check and try again."])

    def test_setaccess_permission_before_arity(self):
        self.assertEqual(self.run_cmd("seller", "!setaccess 5"),
                         ["You don't have the correct permissions."])

    # ---- !adduser: accesslevel<10 -> perms; empty-name quirk allowed ----
    def test_adduser_seller_no_permission(self):
        self.assertEqual(self.run_cmd("seller", "!adduser 5 2 bob"),
                         ["You don't have the correct permissions."])

    def test_adduser_arity(self):
        self.assertEqual(self.run_cmd("mod", "!adduser 5"), ["Syntax incorrect."])

    def test_adduser_higher_level_rejected(self):
        self.assertEqual(self.run_cmd("mod", "!adduser 11 2 bob"),
                         ["You can't give someone a higher accesslevel than your own."])

    def test_adduser_success(self):
        self.assertEqual(self.run_cmd("mod", "!adduser 5 2 bob"),
                         ["User Added with 2 slots."])

    def test_adduser_empty_name_quirk(self):
        # len==3 (no name) passes the <3 arity gate; name becomes "".
        self.assertEqual(self.run_cmd("mod", "!adduser 5 2"),
                         ["User Added with 2 slots."])

    # ---- !removeuser: the access gate denies sub-admins uniformly ----
    def test_removeuser_low_access_denied(self):
        # Registry normalization: a sub-admin now gets the permission error
        # before arity is considered. (The match version checked arity first
        # and returned "Syntax incorrect." for a seller with no argument.)
        self.assertEqual(self.run_cmd("seller", "!removeuser"),
                         ["You don't have the correct permissions."])

    def test_removeuser_permission(self):
        self.assertEqual(self.run_cmd("seller", "!removeuser bob"),
                         ["You don't have the correct permissions."])

    def test_removeuser_not_found(self):
        self.assertEqual(self.run_cmd("admin", "!removeuser ghost"),
                         ["User removal failed. Please check spelling."])

    # ---- !relist / !getback ----
    def test_relist_unknown_user_denied(self):
        # Registry normalization: an unregistered user fails the access=5
        # gate ("permissions"). The match version short-circuited its
        # combined "user==-10 or wrong arity" check to "Syntax incorrect."
        self.assertEqual(self.run_cmd("noone", "!relist 1"),
                         ["You don't have the correct permissions."])

    def test_relist_non_digit(self):
        self.assertEqual(self.run_cmd("seller", "!relist abc"), ["Syntax incorrect."])

    def test_relist_not_found(self):
        self.assertEqual(self.run_cmd("seller", "!relist 1"),
                         ["Item not found.  Please check the uid number and try again."])

    def test_getback_not_found(self):
        self.assertEqual(self.run_cmd("seller", "!getback 999"),
                         ["Item not found.  Please check the uid number and try again."])

    # ---- !add ----
    def test_add_unknown_user(self):
        self.assertEqual(self.run_cmd("noone", "!add 1 100 Iron Ore"),
                         ["You are unable to add items. Request access in [@@https://forums.themanaworld.org/viewtopic.php?f=14&t=14010|ManaMarket's forum thread@@]"])

    def test_add_non_digit(self):
        self.assertEqual(self.run_cmd("seller", "!add a b Iron Ore"), ["Syntax incorrect."])

    def test_add_item_not_found(self):
        # Previously raised KeyError(-10): the weight was computed before the
        # not-found guard. The destructuring refactor moved the weight after
        # the guard, so an unknown item now replies cleanly.
        self.assertEqual(self.run_cmd("seller", "!add 1 100 Nonexistent"),
                         ["Item not found, check spelling."])

    # ---- !help: len 1 welcome, len 2 specific (bare or !prefixed), len>=3 silent ----
    def test_help_welcome(self):
        msgs = self.run_cmd("seller", "!help")
        self.assertEqual(msgs[0], "Welcome to ManaMarket!")

    def test_help_specific_prefixed(self):
        self.assertEqual(self.run_cmd("seller", "!help !buy"),
                         ["!buy <amount> <uid> - Request the purchase of an item or items."])

    def test_help_specific_bare(self):
        self.assertEqual(self.run_cmd("seller", "!help buy"),
                         ["!buy <amount> <uid> - Request the purchase of an item or items."])

    def test_help_extra_args_silent(self):
        self.assertEqual(self.run_cmd("seller", "!help buy now"), [])

    # ---- !getback arity ----
    def test_getback_arity(self):
        self.assertEqual(self.run_cmd("seller", "!getback"), ["Syntax incorrect."])

    # ---- !add happy-parse path: digits + item lookup succeed, then the
    # weight check fires (fixture player has MaxWEIGHT 0). Exercises the
    # amount/price/item-name parsing we are about to destructure. ----
    def test_add_seller_weight_check(self):
        self.assertEqual(self.run_cmd("seller", "!add 1 100 Iron Ore"),
                         ["I've not got enough room left to carry those. Please try again later. "])

    # ---- !irc ----
    def test_irc_arity(self):
        self.assertEqual(self.run_cmd("seller", "!irc"), ["Incorrect syntax."])

    def test_irc_unknown_subcommand_is_silent(self):
        self.assertEqual(self.run_cmd("seller", "!irc maybe"), [])

    def test_irc_off(self):
        self.assertEqual(self.run_cmd("seller", "!irc off"),
                         ["IRC relay mode is now disabled."])

    def test_irc_on(self):
        self.assertEqual(self.run_cmd("seller", "!irc on"),
                         ["IRC relay mode is now enabled (the channel is also bridged to Discord)."])

    def test_irc_on_ignores_extra_args(self):
        self.assertEqual(self.run_cmd("seller", "!irc on please"),
                         ["IRC relay mode is now enabled (the channel is also bridged to Discord)."])

    # ---- !money: registered (in-tree) gate, regardless of level ----
    def test_money_unknown_user_denied(self):
        self.assertEqual(self.run_cmd("noone", "!money"),
                         ["You don't have the correct permissions."])

    def test_money_none_to_collect(self):
        self.assertEqual(self.run_cmd("seller", "!money"),
                         ["You have no money to collect."])

    # ---- !getback has no access gate: ownership is the only guard ----
    def test_getback_demoted_seller_can_reclaim(self):
        # A seller demoted to a mid-level (3) who still owns stock can
        # reclaim it; the old 0<access<5 gate would have denied this.
        main.user_tree.add_user("exseller", 5, 3)
        main.sale_tree.add_item("exseller", 640, 1, 100)  # uid 1
        self.assertEqual(self.run_cmd("exseller", "!getback 1"),
                         ["Where are you?!?  I can't trade with somebody who isn't here!"])

    def test_getback_not_your_item(self):
        # Ownership is enforced for everyone, regardless of level.
        main.user_tree.add_user("midlevel", 0, 3)
        main.sale_tree.add_item("someone_else", 640, 1, 100)  # uid 1
        self.assertEqual(self.run_cmd("midlevel", "!getback 1"),
                         ["That doesn't belong to you!"])

    def test_getback_level0_allowed(self):
        main.user_tree.add_user("stub", 0, 0)
        self.assertEqual(self.run_cmd("stub", "!getback 1"),
                         ["Item not found.  Please check the uid number and try again."])


if __name__ == "__main__":
    unittest.main()
