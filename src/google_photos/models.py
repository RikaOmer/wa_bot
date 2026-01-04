"""Pydantic models for Google Photos API responses."""

from typing import Optional

from pydantic import BaseModel, Field


class TokenResponse(BaseModel):
    """OAuth token response from Google."""

    access_token: str
    refresh_token: Optional[str] = None
    expires_in: int
    token_type: str = "Bearer"
    scope: Optional[str] = None


class Album(BaseModel):
    """Google Photos album."""

    id: str
    title: Optional[str] = None
    product_url: Optional[str] = Field(None, alias="productUrl")
    is_writeable: Optional[bool] = Field(None, alias="isWriteable")
    media_items_count: Optional[str] = Field(None, alias="mediaItemsCount")
    cover_photo_base_url: Optional[str] = Field(None, alias="coverPhotoBaseUrl")
    cover_photo_media_item_id: Optional[str] = Field(
        None, alias="coverPhotoMediaItemId"
    )


class MediaItemResult(BaseModel):
    """Result of uploading a media item."""

    upload_token: Optional[str] = None
    status: Optional[str] = None


class NewMediaItem(BaseModel):
    """A new media item to be created."""

    description: Optional[str] = None
    simple_media_item: dict = Field(..., alias="simpleMediaItem")


class MediaItem(BaseModel):
    """A created media item in Google Photos."""

    id: str
    description: Optional[str] = None
    product_url: Optional[str] = Field(None, alias="productUrl")
    base_url: Optional[str] = Field(None, alias="baseUrl")
    mime_type: Optional[str] = Field(None, alias="mimeType")
    filename: Optional[str] = None


class BatchCreateMediaItemsResponse(BaseModel):
    """Response from batch creating media items."""

    new_media_item_results: list[dict] = Field(
        default_factory=list, alias="newMediaItemResults"
    )

