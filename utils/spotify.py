import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from urllib.parse import urlparse


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
        """
        Extracts track information from any Spotify URL (track, playlist, album, artist, show, episode).
        Handles pagination to get all tracks.
        Returns a list of strings formatted as 'Track Name Artist Name' for YouTube searching.
        """
        parsed_url = urlparse(url)
        if "open.spotify.com" not in parsed_url.netloc:
            return []

        path_parts = parsed_url.path.strip("/").split("/")
        if len(path_parts) < 2:
            return []

        link_type = path_parts[0]
        link_id = path_parts[1]
        tracks = []

        try:
            if link_type == "track":
                track = self.sp.track(link_id)
                if track and track.get("artists"):
                    artist_name = track["artists"][0].get("name", "")
                    tracks.append(f"{track.get('name', '')} {artist_name}")

            elif link_type == "playlist":
                results = self.sp.playlist_items(link_id)
                items = results["items"]
                while results["next"]:
                    results = self.sp.next(results)
                    items.extend(results["items"])
                for item in items:
                    track = item.get("track")
                    if track and track.get("artists"):
                        artist_name = track["artists"][0].get("name", "")
                        tracks.append(f"{track.get('name', '')} {artist_name}")

            elif link_type == "album":
                results = self.sp.album_tracks(link_id)
                items = results["items"]
                while results["next"]:
                    results = self.sp.next(results)
                    items.extend(results["items"])

                album_info = self.sp.album(link_id)
                album_artist = (
                    album_info["artists"][0].get("name", "")
                    if album_info.get("artists")
                    else ""
                )

                for item in items:
                    artist_name = (
                        item["artists"][0].get("name", "")
                        if item.get("artists")
                        else album_artist
                    )
                    tracks.append(f"{item.get('name', '')} {artist_name}")

            elif link_type == "artist":
                results = self.sp.artist_top_tracks(link_id)
                for track in results.get("tracks", []):
                    if track and track.get("artists"):
                        artist_name = track["artists"][0].get("name", "")
                        tracks.append(f"{track.get('name', '')} {artist_name}")

            elif link_type == "show":
                results = self.sp.show_episodes(link_id, limit=50)
                items = results["items"]
                while results["next"]:
                    results = self.sp.next(results)
                    items.extend(results["items"])
                show_info = self.sp.show(link_id)
                publisher = show_info.get("publisher", "Podcast")
                for item in items:
                    tracks.append(f"{item.get('name', '')} {publisher}")

            elif link_type == "episode":
                episode = self.sp.episode(link_id)
                if episode:
                    publisher = episode["show"].get("publisher", "Podcast")
                    tracks.append(f"{episode.get('name', '')} {publisher}")

        except Exception as e:
            print(f"Error processing Spotify URL '{url}': {e}")
            return tracks

        return [track for track in tracks if track.strip()]
