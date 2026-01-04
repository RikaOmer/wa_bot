"""Async client for Google Photos Library API."""

import logging
from typing import Optional

import httpx

from .models import Album, BatchCreateMediaItemsResponse

logger = logging.getLogger(__name__)


class GooglePhotosClient:
    """Async client for interacting with Google Photos Library API."""

    BASE_URL = "https://photoslibrary.googleapis.com/v1"
    UPLOAD_URL = "https://photoslibrary.googleapis.com/v1/uploads"

    def __init__(self, access_token: str):
        """
        Initialize the client with an access token.

        Args:
            access_token: Valid OAuth2 access token for Google Photos.
        """
        self.access_token = access_token
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def client(self) -> httpx.AsyncClient:
        """Lazy-load the HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers={
                    "Authorization": f"Bearer {self.access_token}",
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(60.0),
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "GooglePhotosClient":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    async def create_album(self, title: str) -> Album:
        """
        Create a new album in Google Photos.

        Args:
            title: The title for the new album.

        Returns:
            The created Album object.

        Raises:
            httpx.HTTPStatusError: If the request fails.
        """
        response = await self.client.post(
            f"{self.BASE_URL}/albums",
            json={"album": {"title": title}},
        )
        response.raise_for_status()
        return Album.model_validate(response.json())

    async def get_album(self, album_id: str) -> Album:
        """
        Get an album by ID.

        Args:
            album_id: The Google Photos album ID.

        Returns:
            The Album object.

        Raises:
            httpx.HTTPStatusError: If the request fails.
        """
        response = await self.client.get(f"{self.BASE_URL}/albums/{album_id}")
        response.raise_for_status()
        return Album.model_validate(response.json())

    async def upload_media_bytes(
        self,
        media_bytes: bytes,
        filename: str,
        mime_type: str = "image/jpeg",
    ) -> str:
        """
        Upload media bytes and get an upload token.

        This is the first step of adding media to Google Photos.
        The upload token must then be used with batch_create_media_items.

        Args:
            media_bytes: The raw bytes of the media file.
            filename: The filename for the upload.
            mime_type: The MIME type of the media.

        Returns:
            The upload token to use with batch_create_media_items.

        Raises:
            httpx.HTTPStatusError: If the upload fails.
        """
        # Upload endpoint requires different headers
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as upload_client:
            response = await upload_client.post(
                self.UPLOAD_URL,
                headers={
                    "Authorization": f"Bearer {self.access_token}",
                    "Content-Type": "application/octet-stream",
                    "X-Goog-Upload-Content-Type": mime_type,
                    "X-Goog-Upload-Protocol": "raw",
                    "X-Goog-Upload-File-Name": filename,
                },
                content=media_bytes,
            )
            response.raise_for_status()
            return response.text

    async def batch_create_media_items(
        self,
        upload_tokens: list[str],
        album_id: Optional[str] = None,
        descriptions: Optional[list[str]] = None,
    ) -> BatchCreateMediaItemsResponse:
        """
        Create media items from upload tokens and optionally add to an album.

        Args:
            upload_tokens: List of upload tokens from upload_media_bytes.
            album_id: Optional album ID to add the items to.
            descriptions: Optional list of descriptions for each item.

        Returns:
            BatchCreateMediaItemsResponse with results for each item.

        Raises:
            httpx.HTTPStatusError: If the request fails.
        """
        new_media_items = []
        for i, token in enumerate(upload_tokens):
            item = {
                "simpleMediaItem": {
                    "uploadToken": token,
                }
            }
            if descriptions and i < len(descriptions) and descriptions[i]:
                item["description"] = descriptions[i]
            new_media_items.append(item)

        body: dict = {"newMediaItems": new_media_items}
        if album_id:
            body["albumId"] = album_id

        response = await self.client.post(
            f"{self.BASE_URL}/mediaItems:batchCreate",
            json=body,
        )
        response.raise_for_status()
        return BatchCreateMediaItemsResponse.model_validate(response.json())

    async def upload_to_album(
        self,
        media_bytes: bytes,
        filename: str,
        album_id: str,
        description: Optional[str] = None,
        mime_type: str = "image/jpeg",
    ) -> BatchCreateMediaItemsResponse:
        """
        Convenience method to upload a single photo to an album.

        Args:
            media_bytes: The raw bytes of the media file.
            filename: The filename for the upload.
            album_id: The album to add the photo to.
            description: Optional description for the photo.
            mime_type: The MIME type of the media.

        Returns:
            BatchCreateMediaItemsResponse with the result.
        """
        upload_token = await self.upload_media_bytes(media_bytes, filename, mime_type)
        descriptions = [description] if description else None
        return await self.batch_create_media_items(
            upload_tokens=[upload_token],
            album_id=album_id,
            descriptions=descriptions,
        )

