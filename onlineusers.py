
"""
Copyright 2015, Joseph Botosh <rumly111@gmail.com>

This file is part of tradey, a trading bot in The Mana World
see www.themanaworld.org

This program is free software; you can redistribute it and/or modify it
under the terms of the GNU General Public License as published by the Free
Software Foundation; either version 2 of the License, or (at your option)
any later version.

This program is distributed in the hope that it will be useful, but WITHOUT
ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for
more details.

You should have received a copy of the GNU General Public License along with
this program. If not, see <http://www.gnu.org/licenses/>.

Additionally to the GPL, you are *strongly* encouraged to share any modifications
you do on these sources.
"""

import sys
import logging
import urllib2
import string
import sqlite3
import datetime
import threading
import time
from net.packet_out import whisper
import config

class OnlineUsers:

    def __init__(self, online_url='http://server.themanaworld.org/online-old.txt', update_interval=20):
        self._active = False
        self._timer = 0
        self._thread = threading.Thread(target=self._threadfunc, args=())
        self._url = online_url
        self._update_interval = update_interval
        self.__lock = threading.Lock()
        self.__online_users = []

    @property
    def online_users(self):
        self.__lock.acquire(True)
        users = self.__online_users[:]
        self.__lock.release()
        return users

    def dl_online_list(self):
        """
        Download online.txt, parse it, and return a list of online user nicks.
        If error occurs, return empty list
        """
        try:
            data = urllib2.urlopen(self._url).read()
        except urllib2.URLError, e:
            # self.logger.error("urllib error: %s", e.message)
            print ("urllib error: %s" % e.message)
            return []
        start = string.find(data, '------------------------------\n') + 31
        end = string.rfind(data, '\n\n')
        s = data[start:end]
        return map(lambda n: n[:-5].strip() if n.endswith('(GM) ') else n.strip(),
                   s.split('\n'))

    def _threadfunc(self):
        while self._active:
            if (time.time() - self._timer) > self._update_interval:
                users = self.dl_online_list()
                self.__lock.acquire(True)
                self.__online_users=users
                self.__lock.release()
                self._timer = time.time()
            else:
                time.sleep(1.0)

    def start(self):
        self._active = True
        self._thread.start()

    def stop(self):
        if self._active:
            self._active = False
            self._thread.join()


class SqliteDbManager:

    def __init__(self, dbfile):
        self._active = False
        self._timer = 0
        self._lastseen_thread = threading.Thread(target=self.__lastseen_threadfunc, args=())
        self._mailbox_thread = threading.Thread(target=self.__mailbox_threadfunc, args=())
        self._dbfile = dbfile
        self.mapserv = None
        self._online_manager = OnlineUsers(config.online_txt_url, config.online_txt_interval)

        self.db, self.cur = self._open_sqlite_db(dbfile)
        self.cur.execute('create table if not exists LastSeen(\
                              NICK   text[25] not null unique,\
                              DATE_  date not null)')
        self.cur.execute('create table if not exists MailBox(\
                              ID       integer primary key,\
                              FROM_    text[25] not null,\
                              TO_      text[25] not null,\
                              MESSAGE  text[255] not null)')
        self.cur.execute('create unique index if not exists \
                              FROM_TO_IDX on MailBox(FROM_,TO_)')
        self.db.commit()

    def __del__(self):
        try:
            self.db.close()
        except Exception:
            pass

    def _open_sqlite_db(self, dbfile):
        """
        Open sqlite db, and return tuple (connection, cursor)
        """
        try:
            db = sqlite3.connect(dbfile)
            cur = db.cursor()
        except sqlite3.Error, e:
            # self.logger.error("sqlite3 error: %s", e.message)
            print ("sqlite3 error: %s" % e.message)
            sys.exit(1)
        return db, cur

    def __update_lastseen_info(self, users, db, cur):
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        values = map(lambda u: (u, now), users)
        cur.executemany('replace into LastSeen(NICK,DATE_) values(?,?)',
                        values)
        db.commit()

    def get_lastseen_info(self, nick):
        self.cur.execute('select DATE_ from LastSeen where NICK=?',(nick,))
        self.db.commit()   # NOTE: do I need it?
        row = self.cur.fetchone()
        if row:
            return ('%s was seen %s' % (nick, row[0])).encode('utf-8')
        else:
            return '%s was never seen' % nick

    def __lastseen_threadfunc(self):
        print '__lastseen_threadfunc started'
        db, cur = self._open_sqlite_db(self._dbfile)
        while self._active:
            if (time.time() - self._timer) > 60:
                users = self._online_manager.online_users
                self.__update_lastseen_info(users, db, cur)
                self._timer = time.time()
            else:
                time.sleep(1.0)
        db.close()

    def send_mail(self, from_, to_, message):
        self.cur.execute('replace into MailBox(FROM_,TO_,MESSAGE) values(?,?,?)',
                         (from_,to_,message))
        self.db.commit()

    def get_unread_mails(self, nick, db=None, cur=None):
        if db is None:
            db = self.db
        if cur is None:
            cur = self.cur
        cur.execute('select FROM_,MESSAGE from MailBox where TO_=?',
                    (nick,))
        db.commit()
        mails = cur.fetchall()
        cur.execute('delete from MailBox where TO_=?',
                    (nick,))
        db.commit()
        return mails

    def __mailbox_threadfunc(self):
        print '__mailbox_threadfunc started'
        db, cur = self._open_sqlite_db(self._dbfile)
        while self._active:
            if (time.time() - self._timer) > 60:
                users = self._online_manager.online_users
                for u in users:
                    mail = self.get_unread_mails(u, db, cur)
                    nm = len(mail)
                    if nm > 0:
                        self.mapserv.sendall(whisper(u, "You have %d new mails:" % (nm,)))
                        time.sleep(0.7)
                        for m in mail:
                            msg = ("From %s : %s" % (m[0], m[1])).encode('utf-8')
                            self.mapserv.sendall(whisper(u, msg))
                            time.sleep(0.7)
                self._timer = time.time()
            else:
                time.sleep(1.0)
        db.close()

    def forEachOnline(self, callback, *args):
        users = self._online_manager.online_users
        for u in users:
            callback(u, *args)

    def start(self):
        self._online_manager.start()
        self._active = True
        self._lastseen_thread.start()
        self._mailbox_thread.start()

    def stop(self):
        if self._active:
            self._active = False
            self._lastseen_thread.join()
            self._mailbox_thread.join()
        self._online_manager.stop()


if __name__=='__main__':
    print "You should not run this file. Use main.py"
