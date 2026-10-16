from dataclasses import dataclass

@dataclass(frozen=True)
class Track:
    title: str
    artist: str
    duration: int | None
    source_url: str
    stream_url: str
    requested_by: int = 0
    attribution: str | None = None
    provider: str = 'local'

    @property
    def label(self):
        duration = f' ({self.duration // 60}:{self.duration % 60:02d})' if self.duration is not None else ''
        return f'{self.title} — {self.artist}{duration}'
