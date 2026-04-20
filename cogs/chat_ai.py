from __future__ import annotations

import os

import discord
from discord import app_commands
from discord.ext import commands
from openai import OpenAI

try:
    from utils.theme import BRAND
except Exception:
    BRAND = discord.Color.blurple()


class ChatAI(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.client: OpenAI | None = None
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"

    def _get_client(self) -> OpenAI | None:
        if self.client is not None:
            return self.client
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            return None
        self.client = OpenAI(api_key=api_key)
        return self.client

    def _build_reply(self, user_text: str) -> str:
        client = self._get_client()
        if client is None:
            return "❌ Не задан `OPENAI_API_KEY`. Добавьте переменную окружения и перезапустите бота."

        completion = client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Ты дружелюбный Discord-бот. Отвечай кратко, по делу, на русском языке. "
                        "Не используй опасные инструкции."
                    ),
                },
                {"role": "user", "content": user_text},
            ],
            temperature=0.7,
            max_tokens=500,
        )
        text = (completion.choices[0].message.content or "").strip()
        return text or "Не удалось сгенерировать ответ."

    @app_commands.command(name="chat", description="Поговорить с ИИ-ботом")
    @app_commands.describe(message="Текст вашего сообщения")
    async def chat(self, interaction: discord.Interaction, message: app_commands.Range[str, 1, 1200]):
        await interaction.response.defer()
        try:
            text = self._build_reply(message)
        except Exception as e:
            await interaction.followup.send(f"❌ Ошибка запроса к OpenAI: `{e}`", ephemeral=True)
            return

        if len(text) <= 1900:
            embed = discord.Embed(title="💬 Ответ бота", description=text, color=BRAND)
            await interaction.followup.send(embed=embed)
            return

        # Discord message size fallback.
        chunks = [text[i : i + 1900] for i in range(0, len(text), 1900)]
        for i, chunk in enumerate(chunks, start=1):
            suffix = f" ({i}/{len(chunks)})" if len(chunks) > 1 else ""
            embed = discord.Embed(title=f"💬 Ответ бота{suffix}", description=chunk, color=BRAND)
            await interaction.followup.send(embed=embed)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if not self.bot.user:
            return
        if self.bot.user not in message.mentions:
            return

        text = message.content.replace(f"<@{self.bot.user.id}>", "").replace(f"<@!{self.bot.user.id}>", "").strip()
        if not text:
            await message.reply("Напиши вопрос после упоминания, например: `@бот как дела?`", mention_author=False)
            return

        if len(text) > 1200:
            await message.reply("❌ Слишком длинное сообщение (макс. 1200 символов).", mention_author=False)
            return

        try:
            answer = self._build_reply(text)
        except Exception as e:
            await message.reply(f"❌ Ошибка запроса к OpenAI: `{e}`", mention_author=False)
            return

        if len(answer) <= 1900:
            await message.reply(answer, mention_author=False)
            return

        chunks = [answer[i : i + 1900] for i in range(0, len(answer), 1900)]
        for chunk in chunks:
            await message.reply(chunk, mention_author=False)


async def setup(bot: commands.Bot):
    await bot.add_cog(ChatAI(bot))
