import asyncio
import logging
import os
import re
import ssl
import tempfile
from typing import Any

import aiohttp

from loguru import logger
from pydantic import BaseModel, Field
from vkbottle.bot import Bot, Message
from vkbottle.tools import (
    PhotoMessageUploader,
    DocUploader,
    VoiceMessageUploader,
)

# Disable verbose vkbottle debug logs
logging.getLogger("vkbottle").setLevel(logging.WARNING)
logger.disable("vkbottle")

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.paths import get_media_dir


class VKConfig(BaseModel):
    """Configuration for VK channel."""

    enabled: bool = False
    token: str = ""
    allow_from: list[str] = Field(default_factory=list, alias="allowFrom")
    reaction_id: int = Field(default=10, alias="reactionId")
    reply_to_message: bool = Field(default=True, alias="replyToMessage")

    class Config:
        populate_by_name = True


# --- Markdown to VK HTML conversion -----------------------------------------

# VK messages.send with parse_mode doesn't exist — VK uses inline HTML/BBCode.
# Supported HTML tags: <b>, <i>, <u>, <s>, <br>, <a href="">, <blockquote>
# VK also supports pseudo-BBCode but HTML is more reliable.

def _escape_vk_html(text: str) -> str:
    """Escape HTML special characters for VK."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _markdown_to_vk_html(text: str) -> str:
    """Convert Markdown to VK-compatible HTML.

    VK supports: <b>, <i>, <u>, <s>, <br>, <a href="...">
    """
    # Process code blocks first — render as plain text (VK has no code block)
    # Inline code: `text` → plain text (strip backticks, keep content)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    # Code blocks: ```...``` → plain text, strip fences
    text = re.sub(r"```[^\n]*\n(.*?)```", lambda m: m.group(1), text, flags=re.DOTALL)

    # Escape remaining HTML after stripping code fences
    text = _escape_vk_html(text)

    # Markdown bold: **text** or __text__ → <b>text</b>
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__(.+?)__", r"<b>\1</b>", text)

    # Markdown italic: *text* or _text_ → <i>text</i>
    # Careful: don't match inside ** (already handled) — use lookahead/lookbehind
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", text)
    text = re.sub(r"(?<!\w)_(?!_)(.+?)(?<!\w)_(?!\w)", r"<i>\1</i>", text)

    # Markdown strikethrough: ~~text~~ → <s>text</s>
    text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text)

    # Markdown links: [text](url) → <a href="url">text</a>
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)

    # Markdown headers: # text → <b>text</b> (VK has no heading tag)
    text = re.sub(r"^#{1,6}\s+(.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)

    # Line breaks: \n → <br>
    text = text.replace("\n", "<br>")

    return text


def _tool_hint_to_vk_text(text: str) -> str:
    """Render tool hints as a code block for VK.

    VK renders ``` as a monospace code block, similar to Telegram's
    expandable blockquote but without collapse.
    """
    return f"```\n{_escape_vk_html(text)}\n```" if text else ""


# --- Media helpers ----------------------------------------------------------

_PHOTO_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
_VOICE_EXTS = {".ogg", ".opus"}
_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".flac", ".aac"}


def _get_media_type(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in _PHOTO_EXTS:
        return "photo"
    if ext in _VOICE_EXTS:
        return "voice"
    if ext in _AUDIO_EXTS:
        return "audio"
    return "doc"


# VK message length limit
_VK_MAX_MESSAGE_LEN = 4096


def _split_message(text: str, max_len: int = _VK_MAX_MESSAGE_LEN) -> list[str]:
    """Split text into chunks that fit within VK's message length limit."""
    if len(text) <= max_len:
        return [text]
    chunks = []
    remaining = text
    while remaining:
        if len(remaining) <= max_len:
            chunks.append(remaining)
            break
        # Try to split on <br> or newline
        split_pos = remaining.rfind("<br>", 0, max_len)
        if split_pos == -1:
            split_pos = remaining.rfind("\n", 0, max_len)
        if split_pos == -1:
            split_pos = max_len
        chunks.append(remaining[:split_pos])
        remaining = remaining[split_pos:].lstrip("<br>").lstrip()
    return chunks


class VKChannel(BaseChannel):
    """VK channel implementation for nanobot using vkbottle."""

    name: str = "vk"
    display_name: str = "VKontakte"

    def __init__(self, config: Any, bus: MessageBus):
        super().__init__(config, bus)
        if isinstance(config, dict):
            self.config = VKConfig(**config)
        else:
            self.config = config

        self.bot: Bot | None = None
        self._task: asyncio.Task | None = None

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return {
            "enabled": False,
            "token": "YOUR_VK_GROUP_TOKEN",
            "allow_from": ["*"],
            "replyToMessage": True,
        }

    async def _download_media(self, url: str, ext: str = ".jpg") -> str | None:
        """Download media from URL to the nanobot media directory."""
        try:
            # VK userapi.com servers sometimes fail SSL cert verification on Windows.
            # Use certifi CA bundle as fallback when system certs are missing.
            ssl_ctx = ssl.create_default_context()
            try:
                import certifi
                ssl_ctx.load_verify_locations(certifi.where())
            except ImportError:
                pass  # fall back to system certs

            async with aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(ssl=ssl_ctx)
            ) as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        media_dir = get_media_dir("vk")
                        fd, path = tempfile.mkstemp(suffix=ext, prefix="vk_media_", dir=str(media_dir))
                        with os.fdopen(fd, "wb") as f:
                            f.write(data)
                        return path
                    else:
                        logger.error(f"Failed to download media: HTTP {resp.status}")
                        return None
        except Exception as e:
            logger.error(f"Error downloading media: {e}")
            return None

    async def _upload_photo(self, file_path: str, peer_id: int) -> str | None:
        """Upload a photo to VK and return attachment string like 'photo123_456'."""
        try:
            uploader = PhotoMessageUploader(self.bot.api)
            with open(file_path, "rb") as f:
                photo = await uploader.upload(f, peer_id=peer_id)
            return uploader.generate_attachment_string(photo)
        except Exception as e:
            logger.error(f"Failed to upload photo to VK: {e}")
            return None

    async def _upload_doc(self, file_path: str) -> str | None:
        """Upload a document to VK and return attachment string."""
        try:
            uploader = DocUploader(self.bot.api)
            with open(file_path, "rb") as f:
                doc = await uploader.upload(f)
            return uploader.generate_attachment_string(doc)
        except Exception as e:
            logger.error(f"Failed to upload doc to VK: {e}")
            return None

    async def _upload_voice(self, file_path: str) -> str | None:
        """Upload a voice message to VK and return attachment string."""
        try:
            uploader = VoiceMessageUploader(self.bot.api)
            with open(file_path, "rb") as f:
                voice = await uploader.upload(f)
            return uploader.generate_attachment_string(voice)
        except Exception as e:
            logger.error(f"Failed to upload voice to VK: {e}")
            return None

    async def start(self) -> None:
        if not self.config.enabled or not self.config.token:
            logger.info("VK channel disabled or missing token")
            return

        self._running = True
        logger.info("Starting VK channel...")

        self.bot = Bot(token=self.config.token)

        @self.bot.on.message()
        async def message_handler(message: Message):
            if not self._running:
                return

            sender_id = str(message.from_id)
            chat_id = str(message.peer_id)
            content = message.text or ""

            # Extract attachments using vkbottle helper methods
            # These are more reliable than manually iterating message.attachments
            media = []

            # Photos
            photos = message.get_photo_attachments()
            if photos:
                for photo in photos:
                    # vkbottle 4.7+: PhotosPhoto has `images` (List[PhotosImage]) + `photo_256`
                    # Older versions had `sizes` (List[PhotosPhotoSize]).
                    # Pick the smallest image >= 400px wide to avoid huge downloads.
                    url = None
                    if getattr(photo, "images", None):
                        imgs = sorted(
                            photo.images,
                            key=lambda s: (s.width or 0) * (s.height or 0),
                        )
                        for img in imgs:
                            if (img.width or 0) >= 400 and img.url:
                                url = img.url
                                break
                        if not url and imgs and imgs[-1].url:
                            url = imgs[-1].url  # fallback to largest
                    elif getattr(photo, "sizes", None):
                        sizes = sorted(
                            photo.sizes,
                            key=lambda s: (s.width or 0) * (s.height or 0),
                        )
                        for s in sizes:
                            if (s.width or 0) >= 400 and s.url:
                                url = s.url
                                break
                        if not url and sizes and sizes[-1].url:
                            url = sizes[-1].url
                    elif getattr(photo, "photo_256", None):
                        url = photo.photo_256

                    if url:
                        local_path = await self._download_media(url, ext=".jpg")
                        if local_path:
                            media.append(local_path)

            # Voice messages (audio_message)
            voices = message.get_audio_message_attachments()
            if voices:
                for voice in voices:
                    if voice.link_ogg:
                        local_path = await self._download_media(voice.link_ogg, ext=".ogg")
                        if local_path:
                            media.append(local_path)

            # Documents
            docs = message.get_doc_attachments()
            if docs:
                for doc in docs:
                    if doc.url:
                        ext = os.path.splitext(doc.title)[1] if doc.title else ".bin"
                        local_path = await self._download_media(doc.url, ext=ext)
                        if local_path:
                            media.append(local_path)

            # Extract reply context if any
            reply_ctx = None
            if message.reply_message:
                reply_text = message.reply_message.text or ""
                if reply_text:
                    truncated = reply_text[:100] + "..." if len(reply_text) > 100 else reply_text
                    reply_ctx = f"[Reply to: {truncated}]"

            if reply_ctx:
                content = f"{reply_ctx}\n{content}" if content else reply_ctx

            if not content and not media:
                content = "[empty message]"

            logger.debug(f"VK message from {sender_id}: {content[:50]}...")

            # Fire and forget typing and reaction
            async def _set_typing_and_reaction():
                if message.conversation_message_id and self.config.reaction_id > 0:
                    try:
                        await self.bot.api.request(
                            "messages.sendReaction",
                            {
                                "peer_id": int(chat_id),
                                "cmid": message.conversation_message_id,
                                "reaction_id": self.config.reaction_id,
                            },
                        )
                    except Exception as e:
                        logger.debug(f"Failed to set reaction: {e}")

                try:
                    await self.bot.api.messages.set_activity(
                        peer_id=int(chat_id),
                        type="typing",
                    )
                except Exception as e:
                    logger.debug(f"Failed to set typing status: {e}")

            asyncio.create_task(_set_typing_and_reaction())

            await self._handle_message(
                sender_id=sender_id,
                chat_id=chat_id,
                content=content,
                media=media,
                metadata={
                    "message_id": message.id,
                    "conversation_message_id": message.conversation_message_id,
                },
            )

        self._task = asyncio.create_task(self.bot.run_polling())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("VK channel stopped")

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message back to VK."""
        if not self._running or not self.bot:
            return

        logger.info(f"Sending to VK chat {msg.chat_id}: {msg.content[:50]}...")

        peer_id = int(msg.chat_id)

        # Build reply_to from metadata
        reply_to = None
        if self.config.reply_to_message:
            cmid = msg.metadata.get("conversation_message_id")
            if cmid:
                reply_to = int(cmid)

        # Upload and send media files
        attachments = []
        for media_path in (msg.media or []):
            try:
                media_type = _get_media_type(media_path)
                attachment = None

                if media_type == "photo":
                    attachment = await self._upload_photo(media_path, peer_id)
                elif media_type == "voice":
                    attachment = await self._upload_voice(media_path)
                elif media_type == "audio":
                    # VK audio upload requires artist/title — send as doc
                    attachment = await self._upload_doc(media_path)
                else:
                    attachment = await self._upload_doc(media_path)

                if attachment:
                    # Send each media as a separate message (VK limitation)
                    send_kwargs = {
                        "peer_id": peer_id,
                        "attachment": attachment,
                        "random_id": 0,
                    }
                    if reply_to:
                        send_kwargs["reply_to"] = reply_to
                    await self.bot.api.messages.send(**send_kwargs)
                    # Only reply_to the first message in the chain
                    reply_to = None
                else:
                    logger.error(f"Failed to upload media: {media_path}")
            except Exception as e:
                logger.error(f"Failed to send media {media_path}: {e}")

        # Send text content
        text = msg.content
        if text and text != "[empty message]":
            is_tool_hint = bool(msg.metadata.get("_tool_hint"))
            if is_tool_hint:
                html = _tool_hint_to_vk_text(text)
            else:
                html = _markdown_to_vk_html(text)

            chunks = _split_message(html)
            for chunk in chunks:
                send_kwargs = {
                    "peer_id": peer_id,
                    "message": chunk,
                    "random_id": 0,
                }
                if reply_to:
                    send_kwargs["reply_to"] = reply_to
                try:
                    await self.bot.api.messages.send(**send_kwargs)
                    # Only reply_to the first message
                    reply_to = None
                except Exception as e:
                    logger.error(f"Failed to send VK message: {e}")
                    raise