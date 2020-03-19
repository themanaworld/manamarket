import sys
import threading
import irc.client
import re
from net.packet_out import whisper
import config

replace_map = {
    # colors (we could use mIRC colors but we're just stripping)
    "##0": "", "##1": "", "##2": "", "##3": "", "##4": "",
    "##5": "", "##6": "", "##7": "", "##8": "", "##9": "",
    # afk color
    "##a": "",
    # bold
    "##B": "__", "##b": "__",
    # emotes (we're using discord names)
    r"%%0": ":grinning:",
    r"%%1": ":slightly_smiling_face:",
    r"%%2": ":wink:",
    r"%%3": ":slightly_frowning_face:",
    r"%%4": ":open_mouth:",
    r"%%5": ":neutral_face:",
    r"%%6": ":worried:",
    r"%%7": ":sunglasses:",
    r"%%8": ":grin:",
    r"%%9": ":rage:",
    r"%%:": ":yum:",
    r"%%;": ":blush:",
    r"%%<": ":sob:",
    r"%%=": ":smiling_imp:",
    r"%%>": ":no_mouth:",
    r"%%?": ":ninja:",
    r"%%@": ":nerd:",
    r"%%A": ":star:",
    r"%%B": ":question:",
    r"%%C": ":exclamation:",
    r"%%D": ":bulb:",
    r"%%E": ":arrow_right:",
    r"%%F": ":heart:",
    r"%%G": ":smile:",
    r"%%H": ":upside_down:",
    r"%%I": ":wink:",
    r"%%J": ":fearful:",
    r"%%K": ":scream:",
    r"%%L": ":imp:",
    r"%%M": ":flushed:",
    r"%%N": ":smiley:",
    r"%%O": ":woozy_face:",
    r"%%P": ":rage:",
    r"%%Q": ":yum:",
    r"%%R": ":smirk:",
    r"%%S": ":cry:",
    r"%%T": ":smiling_imp:",
    r"%%U": ":face_with_raised_eyebrow:",
    r"%%V": ":ninja:",
    r"%%W": ":angry:",
    r"%%X": ":star2:",
    r"%%Y": ":grey_question:",
    r"%%Z": ":grey_exclamation:",
    r"%%[": ":speech_left:",
    r"%%\\": ":rolling_eyes:",
    r"%%]": ":heart_eyes:",
    r"%%^": ":sick:",
    r"%%_": ":japanese_ogre:",
    r"%%`": ":pouting_cat:",
    r"%%a": ":laughing:",
    r"%%b": ":relaxed:",
    r"%%c": ":dizzy_face:",
    r"%%d": ":facepalm:",
    r"%%e": ":face_with_symbols_over_mouth:",
    r"%%f": ":tired_face:",
    r"%%g": ":innocent:",
    r"%%h": ":angry:",
    r"%%i": ":cold_sweat:",
    r"%%j": ":speech_baloon:",
    r"%%k": ":swearing:",
    r"%%l": ":smiley_cat:",
    r"%%m": ":sleeping:",
    r"%%n": ":unamused:",
    r"%%o": ":alien:",
    r"%%p": ":smiling_imp:",
    r"%%q": ":jack_o_lantern:",
    r"%%r": ":no_mouth:",
    r"%%s": ":hearts:",
    r"%%t": ":money_mouth:",
}

class IRCBot:

    def __init__(self):
        self._client_thread = threading.Thread(target=self.__client_threadfunc, args=())
        self.conn = None
        self._active = False
        self._ready = False
        self._reactor = None
        self.broadcastFunc = None

    def __client_threadfunc(self):
        print '__client_threadfunc started'
        self._reactor = irc.client.Reactor()
        try:
            self.conn = self._reactor.server().connect(config.irc_server, config.irc_port, config.irc_nick, password=config.irc_password)
        except irc.client.ServerConnectionError:
            print(sys.exc_info()[1])
            raise SystemExit(1)

        self.conn.add_global_handler("welcome", self.__on_connect)
        self.conn.add_global_handler("join", self.__on_join)
        self.conn.add_global_handler("pubmsg", self.__on_pubmsg)
        self.conn.add_global_handler("disconnect", self.__on_disconnect)

        while self._active:
            self._reactor.process_once(timeout=1)

    def __on_connect(self, conn, event):
        print "Connected to IRC on %s:%i" % (config.irc_server, config.irc_port)
        if irc.client.is_channel(config.irc_channel):
            self.conn.join(config.irc_channel)

    def __on_join(self, conn, event):
        print "Joined channel %s" % config.irc_channel
        self._ready = True

    def __on_pubmsg(self, conn, event):
        self.broadcastFunc(event.source.nick, event.arguments[0])

    def __on_disconnect(self, conn, event):
        self.stop()

    def isAFK(self, msg):
        lower = msg.lower()
        if lower[1:3] == "afk" or lower[0:2] == "afk" or lower[0:2] == "##a":
            return True # don't relay AFK messages
        return False

    # strip manaplus formatting
    def manaplusToIRC(self, msg):
        for manaplus, literal in replace_map.items():
            msg = msg.replace(manaplus, literal)
        # now that we're done, return it
        return msg

    def send(self, nick, msg):
        if not self._ready:
            return
        msg = self.manaplusToIRC(msg)
        if not msg:
            return # if the message is empty, discard it
        if msg[:1] == "!":
            self.conn.privmsg(config.irc_channel, "Command sent from TMW by %s:" % nick)
            self.conn.privmsg(config.irc_channel, msg)
        else:
            self.conn.privmsg(config.irc_channel, "<%s> %s" % (nick, msg))

    def start(self):
        self._active = True
        self._client_thread.start()

    def stop(self):
        self._ready = False
        if self._active:
            self._active = False
            self._client_thread.join()


if __name__=='__main__':
    print "You should not run this file. Use main.py"
