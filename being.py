#!/usr/bin/python
"""
Copyright 2011, Dipesh Amin <yaypunkrock@gmail.com>
Copyright 2011, Stefan Beller <stefanbeller@googlemail.com>

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

def job_type(job):
    if (job <= 25 or (job >= 4001 and job <= 4049)):
        return "player"
    elif (job >= 46 and job <= 1000):
        return "npc"
    elif (job > 1000 and job <= 2000):
        return "monster"
    elif (job == 45):
        return "portal"

class BeingManager:
    def __init__(self):
        self.container = {}

    def findId(self, name, type="player"):
        for i in self.container:
           if self.container[i].name == name and self.container[i].type == type:
                return i
        return -10

class Being:
    def __init__(self, being_id, job):
        self.id = being_id
        self.name = ""
        self.x = 0
        self.y = 0
        self.action = ""
        self.job = job
        self.target = 0
        self.type = job_type(job)

if __name__ == '__main__':
    print "Do not run this file directly. Run main.py"
