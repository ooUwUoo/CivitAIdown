"""CivitAI API 数据模型 - 基于 pydantic v2。

对应 CivitAI REST API 响应结构：
- GET /v1/models/{id} -> ModelInfo
- GET /v1/model-versions/{id} -> VersionInfo
- POST /v1/model-versions/by-hash -> VersionInfo | None

字段命名：内部使用 snake_case，API 响应使用 camelCase，
通过 Field alias 映射真实 API 字段。
"""

from __future__ import annotations

from typing import Any

from pydantic import AliasGenerator, BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

__all__ = [
    "ParsedUrl",
    "CreatorInfo",
    "FileInfo",
    "ImageInfo",
    "VersionInfo",
    "ModelInfo",
]


def _camel_alias_generator() -> AliasGenerator:
    return AliasGenerator(
        alias=to_camel,
    )


_camel_config = ConfigDict(
    extra="allow",
    populate_by_name=True,
    alias_generator=to_camel,
)


class ParsedUrl(BaseModel):
    model_id: int
    version_id: int | None = None
    site_url: str = "https://civitai.com"


class CreatorInfo(BaseModel):
    model_config = _camel_config

    username: str
    image: str | None = None


class FileInfo(BaseModel):
    model_config = _camel_config

    id: int
    name: str
    size_kb: float = Field(default=0.0, alias="sizeKB")
    pickle_scan_message: str | None = None
    pickle_scan_result: str | bool | None = None
    virus_scan_result: str | None = None
    scan_result: str | None = None
    download_url: str | None = Field(default=None, alias="downloadUrl")
    type: str | None = None
    hashes: dict[str, str] | None = Field(default=None, alias="hashes")
    primary: bool | None = Field(default=None, alias="primary")
    override_name: str | None = Field(default=None, alias="overrideName")
    scanned_at: str | None = Field(default=None, alias="scannedAt")
    virus_scan_message: str | None = Field(default=None, alias="virusScanMessage")
    file_metadata: dict[str, Any] | None = Field(default=None, alias="metadata")


class ImageInfo(BaseModel):
    model_config = _camel_config

    url: str
    nsfw: int | str | None = None
    nsfw_level: int | None = Field(default=None, alias="nsfwLevel")
    width: int | None = None
    height: int | None = None
    hash: str | None = None
    type: str | None = None
    metadata: dict[str, Any] | None = None
    meta: dict[str, Any] | None = None
    size_bytes: int | None = None
    minor: bool = False
    poi: bool = False
    availability: str = "Public"
    on_site: bool = Field(default=False, alias="onSite")
    remix_of_id: int | None = Field(default=None, alias="remixOfId")


class VersionInfo(BaseModel):
    model_config = _camel_config

    id: int
    model_id: int | None = None
    name: str
    description: str | None = None
    base_model: str | None = Field(default=None, alias="baseModel")
    created_at: str | None = Field(default=None, alias="createdAt")
    updated_at: str | None = Field(default=None, alias="updatedAt")
    status: str | None = None
    published_at: str | None = Field(default=None, alias="publishedAt")
    download_url: str | None = Field(default=None, alias="downloadUrl")
    trained_words: list[str] = Field(default_factory=list, alias="trainedWords")
    files: list[FileInfo] = Field(default_factory=list, alias="files")
    images: list[ImageInfo] = Field(default_factory=list, alias="images")
    stats: dict[str, Any] | None = None
    nsfw_level: int | None = Field(default=None, alias="nsfwLevel")
    base_model_type: str | None = Field(default=None, alias="baseModelType")
    upload_type: str | None = Field(default=None, alias="uploadType")
    usage_control: str | None = Field(default=None, alias="usageControl")
    licensing_fee: int | None = Field(default=None, alias="licensingFee")
    air: str | None = None


class ModelInfo(BaseModel):
    model_config = _camel_config

    id: int
    name: str
    description: str | None = None
    type: str | None = None
    nsfw: bool = False
    poi: bool = False
    allow_no_credit: bool | None = Field(default=None, alias="allowNoCredit")
    allow_commercial_use: Any = Field(default=None, alias="allowCommercialUse")
    allow_derivatives: bool | None = Field(default=None, alias="allowDerivatives")
    allow_different_license: bool | None = Field(default=None, alias="allowDifferentLicense")
    creator: CreatorInfo | None = None
    tags: list[str] = Field(default_factory=list)
    stats: dict[str, Any] | None = None
    versions: list[VersionInfo] = Field(default_factory=list, alias="modelVersions")

    @staticmethod
    def parse_commercial_use(value: Any) -> list[str] | None:
        if value is None:
            return None
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            value = value.strip()
            if value.startswith("{") and value.endswith("}"):
                items = [s.strip() for s in value[1:-1].split(",")]
                return items
        return None
