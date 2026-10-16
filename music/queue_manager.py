import asyncio
import random
from collections import deque

class GuildQueue:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.upcoming = deque()
        self.current = None
        self.volume = 0.5

    def remove(self, index):
        if index < 1 or index > len(self.upcoming):
            raise ValueError('Queue index is out of range.')
        track = self.upcoming[index - 1]
        del self.upcoming[index - 1]
        return track

    def shuffle(self):
        if len(self.upcoming) < 2:
            raise ValueError('Add at least two upcoming songs to shuffle.')
        tracks = list(self.upcoming)
        random.shuffle(tracks)
        self.upcoming.clear()
        self.upcoming.extend(tracks)
        return len(tracks)
