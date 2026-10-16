from dataclasses import replace
from urllib.parse import urlsplit
from providers.spotify import unavailable

class Resolver:
    def __init__(self, provider):
        self.provider = provider

    def resolve(self, query, user_id):
        query = query.strip()
        if not query or len(query) > 1000:
            raise ValueError('Enter a query of 1–1000 characters.')
        if query.startswith(('http:', 'https:')):
            parsed = urlsplit(query)
            if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError('Only approved HTTPS source URLs are accepted.')
            if parsed.hostname in ('open.spotify.com', 'spotify.link'):
                unavailable()
            tracks = self.provider.resolve(query)
        elif query.startswith(('local:', 'playlist:')):
            tracks = self.provider.resolve(query)
        else:
            tracks = self.provider.search(query)
        if not tracks:
            raise ValueError('No authorized catalog recording matches that request.')
        return [replace(t, requested_by=user_id) for t in tracks]
