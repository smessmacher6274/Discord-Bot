import json
import subprocess
import unittest
from unittest.mock import MagicMock, patch
from providers.youtube import YouTube, normalize_url, validate_stream
from providers.router import ProviderRouter
from music.resolver import Resolver
from music.track import Track

class YouTubeTests(unittest.TestCase):
    def test_supported_links(self):
        for url in ['https://youtu.be/2eZVbrO6Z1M', 'https://www.youtube.com/watch?v=2eZVbrO6Z1M&list=abc',
                    'https://m.youtube.com/shorts/2eZVbrO6Z1M']:
            self.assertEqual(normalize_url(url), 'https://www.youtube.com/watch?v=2eZVbrO6Z1M')

    def test_rejects_invalid_links(self):
        for url in ['http://youtube.com/watch?v=2eZVbrO6Z1M', 'https://youtube.com.evil.test/watch?v=2eZVbrO6Z1M',
                    'https://user@youtube.com/watch?v=2eZVbrO6Z1M', 'https://youtube.com:444/watch?v=2eZVbrO6Z1M',
                    'https://youtube.com/watch?v=bad', 'https://youtube.com/playlist?list=abc',
                    'https://127.0.0.1/watch?v=2eZVbrO6Z1M']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                normalize_url(url)

    def test_stream_validation(self):
        self.assertEqual(validate_stream('https://rr1.googlevideo.com/videoplayback'),
                         'https://rr1.googlevideo.com/videoplayback')
        for url in ['file:///secret', 'https://localhost/audio', 'https://googlevideo.com.evil.test/a',
                    'http://rr1.googlevideo.com/a', 'https://user@rr1.googlevideo.com/a']:
            with self.assertRaises(ValueError):
                validate_stream(url)

    @patch('providers.youtube.subprocess.run')
    def test_refreshes_expiring_streams(self, run):
        info = {'title': 'Recording', 'uploader': 'Artist', 'duration': 120,
                'url': 'https://rr1.googlevideo.com/videoplayback'}
        run.return_value = subprocess.CompletedProcess([], 0, json.dumps(info), '')
        youtube = YouTube('C:/node.exe')
        track = youtube.resolve('https://youtu.be/2eZVbrO6Z1M')[0]
        self.assertEqual(track.stream_url, '')
        self.assertEqual(track.provider, 'youtube')
        self.assertEqual(youtube.get_stream(track), info['url'])
        self.assertEqual(run.call_count, 2)
        args = run.call_args.args[0]
        for flag in ['--no-playlist', '--ignore-config', '--skip-download']:
            self.assertIn(flag, args)

    @patch('providers.youtube.subprocess.run')
    def test_timeout_failure_and_live(self, run):
        youtube = YouTube()
        run.side_effect = subprocess.TimeoutExpired('yt-dlp', 75)
        with self.assertRaisesRegex(ValueError, 'too long'):
            youtube.resolve('https://youtu.be/2eZVbrO6Z1M')
        run.side_effect = None
        run.return_value = subprocess.CompletedProcess([], 1, '', 'private diagnostics')
        with self.assertRaisesRegex(ValueError, 'could not provide'):
            youtube.resolve('https://youtu.be/2eZVbrO6Z1M')
        run.return_value = subprocess.CompletedProcess([], 0, json.dumps({'is_live': True}), '')
        with self.assertRaisesRegex(ValueError, 'Live'):
            youtube.resolve('https://youtu.be/2eZVbrO6Z1M')

    def test_routing_and_requester(self):
        local, youtube = MagicMock(), MagicMock()
        local.resolve.return_value = []
        youtube.resolve.return_value = [Track('Recording', 'Artist', 1,
            'https://www.youtube.com/watch?v=2eZVbrO6Z1M', '', provider='youtube')]
        router = ProviderRouter(local, youtube)
        track = Resolver(router).resolve('https://youtu.be/2eZVbrO6Z1M', 42)[0]
        self.assertEqual(track.requested_by, 42)
        router.get_stream(track)
        youtube.get_stream.assert_called_once_with(track)
        local.get_stream.assert_not_called()
