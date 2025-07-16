import spotipy
from spotipy.oauth2 import SpotifyClientCredentials


class SpotifyHelper:
    """A helper class for interacting with the Spotify API."""

    def __init__(self, client_id, client_secret):
        auth = SpotifyClientCredentials(
            client_id=client_id, client_secret=client_secret
        )
        self.sp = spotipy.Spotify(auth_manager=auth)

    def is_spotify_url(self, url):
        """Check if a URL is a Spotify URL."""
        return "open.spotify.com" in url

    def extract_tracks(self, url):
        """Extract track information from a Spotify URL."""
        tracks = []
        if "track" in url:
            track = self.sp.track(url)
            tracks.append(f"{track['name']} {track['artists'][0]['name']}")
        elif "playlist" in url:
            results = self.sp.playlist_items(url)
            for item in results["items"]:
                track = item["track"]
                if track:
                    tracks.append(f"{track['name']} {track['artists'][0]['name']}")
        elif "album" in url:
            results = self.sp.album_tracks(url)
            for item in results["items"]:
                tracks.append(f"{item['name']} {item['artists'][0]['name']}")
        return tracks
