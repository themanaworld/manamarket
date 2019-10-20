import sys
import threading
import irc.client
from net.packet_out import whisper
import config

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

    def send(self, nick, msg):
        if not self._ready:
            return
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
