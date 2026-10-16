from urllib.parse import urlsplit
from providers.youtube import YOUTUBE_HOSTS

class ProviderRouter:
    def __init__(self, local, youtube):
        self.local, self.youtube = local, youtube
        self.tracks = local.tracks

    def search(self, query):
        return self.local.search(query)

    def resolve(self, url):
        local = self.local.resolve(url)
        if local:
            return local
        if urlsplit(url).hostname in YOUTUBE_HOSTS:
            return self.youtube.resolve(url)
        return []

    def get_stream(self, track):
        return (self.youtube if track.provider == 'youtube' else self.local).get_stream(track)

    def prepare_track(self, track):
        return self.youtube.search_track(track) if track.provider == 'youtube_search' else track
