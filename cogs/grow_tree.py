from datetime import datetime, timedelta
import random

import discord
from discord import app_commands
from discord.ext import commands

from utils import JSONHandler, Wallet


class TreeControlView(discord.ui.View):
    def __init__(self, cog: "GrowTree"):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Статус", style=discord.ButtonStyle.secondary, custom_id="tree:status")
    async def status(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self.cog._show_tree(interaction, private=True)

    @discord.ui.button(label="Полить", style=discord.ButtonStyle.primary, custom_id="tree:water")
    async def water(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self.cog._water_tree(interaction, private=True)

    @discord.ui.button(label="Удобрить", style=discord.ButtonStyle.success, custom_id="tree:fertilize")
    async def fertilize(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self.cog._fertilize_tree(interaction, private=True)

    @discord.ui.button(label="Подрезать", style=discord.ButtonStyle.secondary, custom_id="tree:prune")
    async def prune(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self.cog._prune_tree(interaction, private=True)

    @discord.ui.button(label="Лечить", style=discord.ButtonStyle.secondary, custom_id="tree:cure")
    async def cure(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self.cog._cure_tree(interaction, private=True)

    @discord.ui.button(label="Собрать", style=discord.ButtonStyle.success, custom_id="tree:harvest")
    async def harvest(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self.cog._harvest_tree(interaction, private=True)

    @discord.ui.button(label="Квест", style=discord.ButtonStyle.primary, custom_id="tree:quest")
    async def quest(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self.cog._show_tree_quest(interaction, private=True)

    @discord.ui.button(label="Топ", style=discord.ButtonStyle.secondary, custom_id="tree:top")
    async def top(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self.cog._show_tree_top(interaction, private=True)


class GrowTree(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = JSONHandler("data/trees.json")
        self.panel_db = JSONHandler("data/tree_panel.json")
        self.bot.add_view(TreeControlView(self))

    def get_tree(self, guild_id: int, user_id: int) -> dict:
        key = f"{guild_id}.{user_id}"
        tree = self.db.get(key, {})
        if not tree:
            tree = {
                "level": 1,
                "xp": 0,
                "water": 100,
                "health": 100,
                "fertilizer": 2,
                "last_water": None,
                "last_tick": datetime.now().isoformat(),
                "fruits": 0,
                "streak": 0,
                "species": "Яблоня",
                "stage": 0,
                "disease": None,
                "last_harvest": None,
                "last_prune": None,
                "last_quest": None,
                "quest_progress": 0,
                "quest_target": random.randint(3, 8),
                "mutations": 0,
            }
            self.db.set(key, tree)
        return tree

    def save_tree(self, guild_id: int, user_id: int, tree: dict):
        self.db.set(f"{guild_id}.{user_id}", tree)

    def _apply_passive_decay(self, tree: dict):
        now = datetime.now()
        last_tick = datetime.fromisoformat(tree.get("last_tick", now.isoformat()))
        passed_hours = max(0, int((now - last_tick).total_seconds() // 3600))
        if passed_hours > 0:
            water_loss = 5 + (tree["level"] // 10)
            tree["water"] = max(0, tree["water"] - passed_hours * water_loss)
            if tree["water"] == 0:
                tree["health"] = max(0, tree["health"] - passed_hours * 5)
            tree["xp"] += passed_hours * 4

            fruit_growth = max(1, tree["level"] // 4)
            if tree["health"] >= 50:
                tree["fruits"] += (passed_hours // 2) * fruit_growth
            else:
                tree["fruits"] += passed_hours // 3

            if random.random() < min(0.15, passed_hours * 0.02) and tree["disease"] is None:
                tree["disease"] = random.choice(["Тля", "Грибок", "Сухость"])

            if tree["disease"]:
                tree["health"] = max(0, tree["health"] - passed_hours * 2)

            tree["last_tick"] = now.isoformat()

        while tree["xp"] >= self.required_xp(tree["level"]):
            tree["xp"] -= self.required_xp(tree["level"])
            tree["level"] += 1
            tree["stage"] = self.level_to_stage(tree["level"])
            tree["health"] = min(100, tree["health"] + 10)
            if tree["level"] % 15 == 0:
                tree["mutations"] += 1

    def _tree_stage(self, level: int) -> str:
        if level < 5:
            return "🌱 Росток"
        if level < 12:
            return "🌿 Молодое дерево"
        if level < 25:
            return "🌳 Сильное дерево"
        return "🌲 Древо-гигант"

    def level_to_stage(self, level: int) -> int:
        if level < 5:
            return 0
        if level < 12:
            return 1
        if level < 25:
            return 2
        return 3

    def required_xp(self, level: int) -> int:
        return 130 + (level * 35)

    def tree_image_url(self, tree: dict) -> str:
        # Можно заменить на свои изображения (CDN/хостинг сервера).
        if tree.get("health", 100) <= 25:
            return "https://images.unsplash.com/photo-1472141521881-95d0e87e2e39?auto=format&fit=crop&w=1200&q=80"
        if tree.get("disease"):
            return "https://images.unsplash.com/photo-1463320898484-cdee8141c787?auto=format&fit=crop&w=1200&q=80"
        fruits = tree.get("fruits", 0)
        level = tree.get("level", 1)
        if fruits >= 40:
            return "https://images.unsplash.com/photo-1471194402529-8e0f5a675de6?auto=format&fit=crop&w=1200&q=80"
        if fruits >= 10:
            return "https://images.unsplash.com/photo-1567306226416-28f0efdc88ce?auto=format&fit=crop&w=1200&q=80"
        if level >= 20:
            return "https://images.unsplash.com/photo-1448375240586-882707db888b?auto=format&fit=crop&w=1200&q=80"
        if level >= 8:
            return "https://images.unsplash.com/photo-1511497584788-876760111969?auto=format&fit=crop&w=1200&q=80"
        return "https://images.unsplash.com/photo-1441974231531-c6227db76b6e?auto=format&fit=crop&w=1200&q=80"

    def get_eco(self, guild_id: int, user_id: int) -> dict:
        return Wallet.get(guild_id, user_id)

    def save_eco(self, guild_id: int, user_id: int, data: dict):
        Wallet.save(guild_id, user_id, data)

    @app_commands.command(name="tree_panel_setup", description="Создать панель управления Grow a Tree")
    @app_commands.default_permissions(manage_guild=True)
    async def tree_panel_setup(self, interaction: discord.Interaction, channel: discord.TextChannel | None = None):
        target = channel or interaction.channel
        if not isinstance(target, discord.TextChannel):
            await interaction.response.send_message("❌ Укажите текстовый канал", ephemeral=True)
            return
        embed = discord.Embed(
            title="Grow a Tree • Панель",
            description="Управляйте своим деревом кнопками: полив, уход, лечение, сбор урожая и другое.",
            color=discord.Color.green(),
        )
        tree = self.get_tree(interaction.guild.id, interaction.user.id)
        self._apply_passive_decay(tree)
        self.save_tree(interaction.guild.id, interaction.user.id, tree)
        embed.set_image(url=self.tree_image_url(tree))
        await target.send(embed=embed, view=TreeControlView(self))
        self.panel_db.set(str(interaction.guild.id), {"channel_id": target.id})
        await interaction.response.send_message(f"✅ Панель отправлена в {target.mention}", ephemeral=True)

    @app_commands.command(name="tree", description="Показать состояние вашего дерева")
    async def tree(self, interaction: discord.Interaction, member: discord.Member | None = None):
        await self._show_tree(interaction, member)

    async def _show_tree(self, interaction: discord.Interaction, member: discord.Member | None = None, private: bool = False):
        member = member or interaction.user
        tree = self.get_tree(interaction.guild.id, member.id)
        self._apply_passive_decay(tree)
        self.save_tree(interaction.guild.id, member.id, tree)

        need_xp = self.required_xp(tree["level"])
        disease = tree["disease"] if tree["disease"] else "Нет"
        embed = discord.Embed(title=f"Grow a Tree • {member.display_name}", color=discord.Color.green())
        embed.description = f"Стадия: **{self._tree_stage(tree['level'])}** | Вид: **{tree['species']}**"
        embed.add_field(name="Уровень", value=str(tree["level"]), inline=True)
        embed.add_field(name="XP", value=f'{tree["xp"]}/{need_xp}', inline=True)
        embed.add_field(name="Плоды", value=str(tree["fruits"]), inline=True)
        embed.add_field(name="Вода", value=f'{tree["water"]}%', inline=True)
        embed.add_field(name="Здоровье", value=f'{tree["health"]}%', inline=True)
        embed.add_field(name="Удобрение", value=str(tree["fertilizer"]), inline=True)
        embed.add_field(name="Болезнь", value=disease, inline=True)
        embed.add_field(name="Мутации", value=str(tree["mutations"]), inline=True)
        embed.add_field(name="Квест дня", value=f'{tree["quest_progress"]}/{tree["quest_target"]} поливов', inline=True)
        embed.set_image(url=self.tree_image_url(tree))
        await interaction.response.send_message(embed=embed, ephemeral=private)

    @app_commands.command(name="tree_water", description="Полить дерево")
    async def tree_water(self, interaction: discord.Interaction):
        await self._water_tree(interaction)

    async def _water_tree(self, interaction: discord.Interaction, private: bool = False):
        tree = self.get_tree(interaction.guild.id, interaction.user.id)
        self._apply_passive_decay(tree)

        if tree["last_water"]:
            last = datetime.fromisoformat(tree["last_water"])
            if datetime.now() - last < timedelta(minutes=20):
                left = timedelta(minutes=20) - (datetime.now() - last)
                await interaction.response.send_message(
                    f"⏰ Можно полить через {left.seconds // 60} мин", ephemeral=True
                )
                return

        gain = random.randint(22, 38)
        tree["water"] = min(100, tree["water"] + gain)
        tree["xp"] += random.randint(20, 45)
        tree["last_water"] = datetime.now().isoformat()
        tree["streak"] += 1
        tree["quest_progress"] += 1

        if tree["disease"] == "Сухость":
            tree["disease"] = None
            tree["health"] = min(100, tree["health"] + 8)

        if tree["streak"] % 5 == 0:
            tree["fertilizer"] += 1

        # Награда за дневной квест.
        if tree["quest_progress"] >= tree["quest_target"]:
            tree["quest_progress"] = 0
            tree["quest_target"] = random.randint(4, 9)
            bonus = random.randint(250, 650)
            eco = self.get_eco(interaction.guild.id, interaction.user.id)
            eco["balance"] += bonus
            self.save_eco(interaction.guild.id, interaction.user.id, eco)
            quest_msg = f"\n🏅 Квест выполнен! Бонус: **{bonus}** 🪙"
        else:
            quest_msg = ""

        self.save_tree(interaction.guild.id, interaction.user.id, tree)
        embed = discord.Embed(
            title="💧 Полив дерева",
            description=f"Дерево полито (+{gain}% воды, +XP){quest_msg}",
            color=discord.Color.blue(),
        )
        embed.set_image(url=self.tree_image_url(tree))
        await interaction.response.send_message(embed=embed, ephemeral=private)

    @app_commands.command(name="tree_fertilize", description="Использовать удобрение")
    async def tree_fertilize(self, interaction: discord.Interaction):
        await self._fertilize_tree(interaction)

    async def _fertilize_tree(self, interaction: discord.Interaction, private: bool = False):
        tree = self.get_tree(interaction.guild.id, interaction.user.id)
        self._apply_passive_decay(tree)
        if tree["fertilizer"] <= 0:
            await interaction.response.send_message("❌ Нет удобрений. Получайте их за полив или в магазине.", ephemeral=True)
            return
        tree["fertilizer"] -= 1
        tree["xp"] += random.randint(90, 170)
        tree["health"] = min(100, tree["health"] + random.randint(8, 16))
        if tree["disease"] in ("Тля", "Грибок"):
            tree["disease"] = None
        self.save_tree(interaction.guild.id, interaction.user.id, tree)
        embed = discord.Embed(title="🧪 Удобрение", description="Удобрение применено: дерево растет быстрее!", color=discord.Color.green())
        embed.set_image(url=self.tree_image_url(tree))
        await interaction.response.send_message(embed=embed, ephemeral=private)

    @app_commands.command(name="tree_prune", description="Подрезать дерево, чтобы повысить здоровье")
    async def tree_prune(self, interaction: discord.Interaction):
        await self._prune_tree(interaction)

    async def _prune_tree(self, interaction: discord.Interaction, private: bool = False):
        tree = self.get_tree(interaction.guild.id, interaction.user.id)
        self._apply_passive_decay(tree)
        if tree["last_prune"]:
            last = datetime.fromisoformat(tree["last_prune"])
            if datetime.now() - last < timedelta(minutes=30):
                wait = timedelta(minutes=30) - (datetime.now() - last)
                await interaction.response.send_message(f"⏰ Подрезка снова через {wait.seconds // 60} мин", ephemeral=True)
                return
        heal = random.randint(10, 25)
        xp = random.randint(12, 28)
        tree["health"] = min(100, tree["health"] + heal)
        tree["xp"] += xp
        tree["last_prune"] = datetime.now().isoformat()
        self.save_tree(interaction.guild.id, interaction.user.id, tree)
        embed = discord.Embed(
            title="✂️ Подрезка",
            description=f"Подрезка успешна (+{heal}% здоровья, +{xp} XP)",
            color=discord.Color.orange(),
        )
        embed.set_image(url=self.tree_image_url(tree))
        await interaction.response.send_message(embed=embed, ephemeral=private)

    @app_commands.command(name="tree_cure", description="Лечить болезнь дерева")
    async def tree_cure(self, interaction: discord.Interaction):
        await self._cure_tree(interaction)

    async def _cure_tree(self, interaction: discord.Interaction, private: bool = False):
        tree = self.get_tree(interaction.guild.id, interaction.user.id)
        self._apply_passive_decay(tree)
        if not tree["disease"]:
            await interaction.response.send_message("✅ Дерево здорово", ephemeral=True)
            return
        eco = self.get_eco(interaction.guild.id, interaction.user.id)
        price = 500 + tree["level"] * 20
        if eco["balance"] < price:
            await interaction.response.send_message(f"❌ Нужно {price} 🪙 на лечение", ephemeral=True)
            return
        eco["balance"] -= price
        tree["disease"] = None
        tree["health"] = min(100, tree["health"] + 15)
        self.save_eco(interaction.guild.id, interaction.user.id, eco)
        self.save_tree(interaction.guild.id, interaction.user.id, tree)
        embed = discord.Embed(title="💊 Лечение", description=f"Болезнь вылечена за **{price}** 🪙", color=discord.Color.green())
        embed.set_image(url=self.tree_image_url(tree))
        await interaction.response.send_message(embed=embed, ephemeral=private)

    @app_commands.command(name="tree_harvest", description="Собрать плоды дерева")
    async def tree_harvest(self, interaction: discord.Interaction):
        await self._harvest_tree(interaction)

    async def _harvest_tree(self, interaction: discord.Interaction, private: bool = False):
        tree = self.get_tree(interaction.guild.id, interaction.user.id)
        self._apply_passive_decay(tree)
        if tree["last_harvest"]:
            last = datetime.fromisoformat(tree["last_harvest"])
            if datetime.now() - last < timedelta(minutes=15):
                left = timedelta(minutes=15) - (datetime.now() - last)
                await interaction.response.send_message(f"⏰ Сбор снова через {left.seconds // 60} мин", ephemeral=True)
                return
        if tree["fruits"] <= 0:
            await interaction.response.send_message("🍎 Плоды еще не созрели", ephemeral=True)
            return
        fruits = tree["fruits"]
        tree["fruits"] = 0
        tree["last_harvest"] = datetime.now().isoformat()
        self.save_tree(interaction.guild.id, interaction.user.id, tree)

        rarity_roll = random.random()
        if rarity_roll < 0.02:
            rarity, multiplier = "Легендарные", 2.8
        elif rarity_roll < 0.10:
            rarity, multiplier = "Редкие", 1.9
        elif rarity_roll < 0.35:
            rarity, multiplier = "Необычные", 1.35
        else:
            rarity, multiplier = "Обычные", 1.0

        reward = int(fruits * random.randint(28, 45) * multiplier)
        user = self.get_eco(interaction.guild.id, interaction.user.id)
        user["balance"] = user.get("balance", 0) + reward
        self.save_eco(interaction.guild.id, interaction.user.id, user)
        embed = discord.Embed(
            title="🍏 Сбор урожая",
            description=f"Вы собрали {fruits} плодов.\nКачество урожая: **{rarity}**\nПродано за **{reward}** 🪙",
            color=discord.Color.gold(),
        )
        embed.set_image(url=self.tree_image_url(tree))
        await interaction.response.send_message(embed=embed, ephemeral=private)

    @app_commands.command(name="tree_seed", description="Сменить вид дерева")
    async def tree_seed(self, interaction: discord.Interaction, species: str):
        allowed = {"Яблоня", "Груша", "Сакура", "Дуб", "Клён"}
        if species not in allowed:
            await interaction.response.send_message(
                f"❌ Доступные виды: {', '.join(sorted(allowed))}",
                ephemeral=True,
            )
            return
        tree = self.get_tree(interaction.guild.id, interaction.user.id)
        self._apply_passive_decay(tree)
        eco = self.get_eco(interaction.guild.id, interaction.user.id)
        price = 1200
        if eco["balance"] < price:
            await interaction.response.send_message(f"❌ Нужно {price} 🪙", ephemeral=True)
            return
        eco["balance"] -= price
        tree["species"] = species
        tree["xp"] += 60
        self.save_eco(interaction.guild.id, interaction.user.id, eco)
        self.save_tree(interaction.guild.id, interaction.user.id, tree)
        await interaction.response.send_message(f"🌰 Посажен новый вид: **{species}**")

    @app_commands.command(name="tree_quest", description="Статус квеста Grow a Tree")
    async def tree_quest(self, interaction: discord.Interaction):
        await self._show_tree_quest(interaction)

    async def _show_tree_quest(self, interaction: discord.Interaction, private: bool = False):
        tree = self.get_tree(interaction.guild.id, interaction.user.id)
        self._apply_passive_decay(tree)
        self.save_tree(interaction.guild.id, interaction.user.id, tree)
        await interaction.response.send_message(
            f"📜 Квест дня: полить дерево **{tree['quest_target']}** раз.\n"
            f"Прогресс: **{tree['quest_progress']}/{tree['quest_target']}**",
            ephemeral=private,
        )

    @app_commands.command(name="tree_top", description="Топ деревьев сервера")
    async def tree_top(self, interaction: discord.Interaction):
        await self._show_tree_top(interaction)

    async def _show_tree_top(self, interaction: discord.Interaction, private: bool = False):
        guild_id = str(interaction.guild.id)
        root = self.db.data.get(guild_id, {})
        rows = []
        for user_id, tree in root.items():
            score = (
                tree.get("level", 1) * 1000
                + tree.get("xp", 0)
                + tree.get("fruits", 0) * 5
                + tree.get("mutations", 0) * 350
            )
            rows.append((int(user_id), score, tree.get("level", 1)))
        rows.sort(key=lambda x: x[1], reverse=True)

        lines = []
        for i, (uid, score, level) in enumerate(rows[:10], 1):
            member = interaction.guild.get_member(uid)
            name = member.display_name if member else f"Пользователь {uid}"
            lines.append(f"{i}. **{name}** — lvl {level} ({score} очков)")
        text = "\n".join(lines) if lines else "Пока никто не выращивает дерево."
        await interaction.response.send_message(
            embed=discord.Embed(title="🌲 Топ Grow a Tree", description=text),
            ephemeral=private,
        )


async def setup(bot: commands.Bot):
    from utils import target_guild

    g = target_guild()
    if g is None:
        await bot.add_cog(GrowTree(bot))
    else:
        await bot.add_cog(GrowTree(bot), guild=g)
