import asyncio
import logging
import os
import tempfile
from typing import Any
import aiohttp

from loguru import logger
from pydantic import BaseModel, Field
from vkbottle.bot import Bot, Message

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

    class Config:
        populate_by_name = True


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
            "allow_from": ["*"]
        }

    async def _download_media(self, url: str, ext: str = ".jpg") -> str | None:
        """Download media from URL to the nanobot media directory."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        media_dir = get_media_dir("vk")
                        # Generate a unique filename using tempfile but in the media_dir
                        fd, path = tempfile.mkstemp(suffix=ext, prefix="vk_media_", dir=str(media_dir))
                        with os.fdopen(fd, 'wb') as f:
                            f.write(data)
                        return path
                    else:
                        logger.error(f"Failed to download media: HTTP {resp.status}")
                        return None
        except Exception as e:
            logger.error(f"Error downloading media: {e}")
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
            
            # Extract attachments (photos, docs, etc.)
            media = []
            if message.attachments:
                for att in message.attachments:
                    if att.photo:
                        # Get the largest photo URL
                        sizes = sorted(att.photo.sizes, key=lambda s: s.width * s.height, reverse=True)
                        if sizes:
                            url = sizes[0].url
                            local_path = await self._download_media(url, ext=".jpg")
                            if local_path:
                                media.append(local_path)
                    elif att.doc and att.doc.url:
                        url = att.doc.url
                        ext = os.path.splitext(att.doc.title)[1] if att.doc.title else ".bin"
                        local_path = await self._download_media(url, ext=ext)
                        if local_path:
                            media.append(local_path)
            
            # Extract reply context if any
            reply_ctx = None
            if message.reply_message:
                reply_text = message.reply_message.text or ""
                if reply_text:
                    reply_ctx = f"[Reply to: {reply_text[:100] + '...' if len(reply_text) > 100 else reply_text}]"
            
            if reply_ctx:
                content = f"{reply_ctx}\n{content}" if content else reply_ctx
                
            if not content and not media:
                content = "[empty message]"
                
            logger.debug(f"VK message from {sender_id}: {content[:50]}...")
            
            # Fire and forget typing and reaction to avoid blocking message processing
            async def _set_typing_and_reaction():
                # Try to set reaction first if conversation_message_id is available
                if message.conversation_message_id and self.config.reaction_id > 0:
                    try:
                        await self.bot.api.request(
                            "messages.sendReaction",
                            {
                                "peer_id": int(chat_id),
                                "cmid": message.conversation_message_id,
                                "reaction_id": self.config.reaction_id
                            }
                        )
                    except Exception as e:
                        logger.debug(f"Failed to set reaction: {e}")
                
                # Set "typing" status
                try:
                    await self.bot.api.messages.set_activity(
                        peer_id=int(chat_id),
                        type="typing"
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
                    "conversation_message_id": message.conversation_message_id
                }
            )

        # Start the polling loop in the background
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
        
        try:
            # vkbottle handles random_id automatically if not provided, 
            # but it's good practice to provide 0 for auto-generation
            await self.bot.api.messages.send(
                peer_id=int(msg.chat_id),
                message=msg.content,
                random_id=0
            )
        except Exception as e:
            logger.error(f"Failed to send VK message: {e}")
            raise