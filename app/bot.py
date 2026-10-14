"""Client Discord: nhận @mention, tạo thread, gọi LLM, trả lời."""
from __future__ import annotations

import asyncio
import logging
import time

import discord

from .config import Config
from .history import History
from .llm import LLMError, make_llm
from .prompt import SYSTEM_PROMPT
from .ratelimit import RateLimiter
from .splitter import split_message
from .store import ThreadStore

log = logging.getLogger("searchbot")


def thread_name(text: str) -> str:
    one = " ".join(text.split())
    return (one[:90] or "Câu hỏi") + ("…" if len(one) > 90 else "")


def strip_mention(content: str, bot_id: int) -> str:
    for token in (f"<@{bot_id}>", f"<@!{bot_id}>"):
        content = content.replace(token, "")
    return content.strip()


def role_of(user_id: int, owner_id: int | None) -> str:
    return "chủ bot" if owner_id is not None and user_id == owner_id else "thành viên"


def build_question(name: str, user_id: int, owner_id: int | None, text: str) -> str:
    return f"[Người hỏi: {name} | {user_id} | {role_of(user_id, owner_id)}]\n{text}"


class SearchBot(discord.Client):
    def __init__(self, cfg: Config, llm=None, store: ThreadStore | None = None):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none())
        self.cfg = cfg
        self.llm = llm or make_llm(cfg, SYSTEM_PROMPT)
        self.history = History(cfg.history_turns)
        self.limiter = RateLimiter(cfg.rate_limit_per_min)
        self._locks: dict[int, asyncio.Lock] = {}  # mỗi thread xử lý lần lượt, tránh lẫn lịch sử
        self.bot_threads = store if store is not None else ThreadStore(cfg.data_dir + "/threads.json")
        self.tree = discord.app_commands.CommandTree(self)
        self._register_commands()

    def _register_commands(self) -> None:
        @self.tree.command(name="reset", description="Xóa ngữ cảnh hội thoại của thread này")
        async def reset(interaction: discord.Interaction):
            ch = interaction.channel
            if ch is not None and ch.id in self.bot_threads:
                self.history.clear(ch.id)
                await interaction.response.send_message("Đã xóa ngữ cảnh của thread này.", ephemeral=True)
            else:
                await interaction.response.send_message("Lệnh này chỉ dùng trong thread của bot.", ephemeral=True)

        @self.tree.command(name="help", description="Cách dùng bot")
        async def help_(interaction: discord.Interaction):
            await interaction.response.send_message(
                "@mention mình kèm câu hỏi, mình sẽ tìm web và trả lời trong một thread. "
                "Trong thread đó bạn hỏi tiếp không cần @mention. `/reset` để xóa ngữ cảnh.", ephemeral=True)

    async def setup_hook(self) -> None:
        await self.tree.sync()

    async def on_ready(self):
        log.info("Đã đăng nhập: %s (%s)", self.user, self.user.id if self.user else "?")

    def _allowed(self, message: discord.Message) -> bool:
        c = self.cfg
        if c.allowed_user_ids and message.author.id not in c.allowed_user_ids and message.author.id != c.owner_id:
            return False
        ch = message.channel
        parent_id = getattr(ch, "parent_id", None)
        if c.allowed_channel_ids and ch.id not in c.allowed_channel_ids and parent_id not in c.allowed_channel_ids:
            return False
        return True

    def _addressed(self, message: discord.Message) -> bool:
        if self.user and self.user in message.mentions:
            return True
        # trong thread do bot tạo, người dùng không cần @mention lại
        return isinstance(message.channel, discord.Thread) and message.channel.id in self.bot_threads

    async def on_message(self, message: discord.Message):
        if message.author.bot or not self.user or not self._addressed(message) or not self._allowed(message):
            return
        question = strip_mention(message.content, self.user.id)
        if not question:
            await message.reply("Bạn muốn hỏi gì? Hãy @mention mình kèm câu hỏi.", mention_author=False)
            return
        if not self.limiter.allow(message.author.id):
            await message.reply("Bạn hỏi nhanh quá, đợi một chút rồi hỏi tiếp nhé.", mention_author=False)
            return

        thread = message.channel
        if not isinstance(thread, discord.Thread):
            try:
                thread = await message.create_thread(name=thread_name(question), auto_archive_duration=1440)
            except discord.HTTPException:
                log.exception("Không tạo được thread, trả lời trực tiếp")
                thread = message.channel
        if isinstance(thread, discord.Thread):
            self.bot_threads.add(thread.id)

        lock = self._locks.setdefault(thread.id, asyncio.Lock())
        async with lock, thread.typing():
            t0 = time.monotonic()
            log.info("câu hỏi: user=%s thread=%s độ dài=%d", message.author.id, thread.id, len(question))
            full = build_question(message.author.display_name, message.author.id, self.cfg.owner_id, question)
            try:
                answer = await self.llm.answer(self.history.get(thread.id), full, self.cfg.max_tool_rounds)
            except LLMError as e:
                # người dùng chỉ thấy câu thân thiện; chi tiết nằm ở log
                log.warning("LLM lỗi: %s", e)
                await thread.send(str(e))
                return
            except Exception:
                log.exception("Lỗi không lường trước")
                await thread.send("Có lỗi nội bộ, mình không trả lời được. Thử lại sau nhé.")
                return
            log.info("đã trả lời: thread=%s %.1fs, %d ký tự", thread.id, time.monotonic() - t0, len(answer))
            self.history.add_turn(thread.id, full, answer)
            for chunk in split_message(answer):
                await thread.send(chunk)
