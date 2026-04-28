import asyncio
import socket
import struct
import uuid
from dataclasses import dataclass
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from utils import JSONHandler

try:
    from utils.theme import BRAND
except Exception:
    BRAND = discord.Color.blurple()


@dataclass
class MonitoredServer:
    sid: str
    name: str
    game: str  # "source" | "minecraft"
    host: str
    port: int

    @property
    def address(self) -> str:
        return f"{self.host}:{self.port}"

    @property
    def steam_url(self) -> str | None:
        if self.game == "source":
            # Discord кнопки не принимают scheme steam://, поэтому заворачиваем в HTTPS линк.
            # Steam откроет внешнюю ссылку, а затем уже steam://connect/...
            steam = f"steam://connect/{self.address}"
            return f"https://steamcommunity.com/linkfilter/?url={steam}"
        return None


def _normalize_guild_cfg(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {"panel": {}, "servers": []}
    if "servers" in raw or "panel" in raw:
        return {
            "panel": raw.get("panel") or {},
            "servers": raw.get("servers") or [],
        }
    if "channel_id" in raw:
        return {
            "panel": {"channel_id": raw["channel_id"], "message_id": raw.get("message_id")},
            "servers": [],
        }
    return {"panel": {}, "servers": []}


def _query_source_sync(host: str, port: int) -> dict[str, Any]:
    packet = b"\xFF\xFF\xFF\xFFTSource Engine Query\x00"
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(2.5)
    try:
        sock.sendto(packet, (host, port))
        data, _ = sock.recvfrom(4096)
        if not data.startswith(b"\xFF\xFF\xFF\xFFI"):
            return {"online": False}

        p = 6
        end = data.find(b"\x00", p)
        server_name = data[p:end].decode("utf-8", errors="ignore")
        p = end + 1
        end = data.find(b"\x00", p)
        game_map = data[p:end].decode("utf-8", errors="ignore")
        p = end + 1
        end = data.find(b"\x00", p)
        p = end + 1
        end = data.find(b"\x00", p)
        p = end + 1
        idx = p
        idx += 2
        players = data[idx]
        max_players = data[idx + 1]

        return {
            "online": True,
            "name": server_name or "Unknown",
            "map": game_map or "unknown",
            "players": int(players),
            "max_players": int(max_players),
        }
    except (socket.timeout, OSError, IndexError, ValueError, struct.error):
        return {"online": False}
    finally:
        sock.close()


def _query_minecraft_fallback(host: str, port: int) -> dict[str, Any]:
    try:
        sock = socket.create_connection((host, port), timeout=3.0)
        sock.close()
        return {
            "online": True,
            "version": "?",
            "players": 0,
            "max_players": 0,
            "motd": "Установите `mcstatus` для полного статуса: `pip install mcstatus`",
        }
    except OSError:
        return {"online": False}


def _query_minecraft_sync(host: str, port: int) -> dict[str, Any]:
    try:
        from mcstatus import JavaServer

        server = JavaServer(host, port)
        status = server.status()
        motd = status.description
        if hasattr(motd, "to_plain"):
            motd_text = motd.to_plain()
        else:
            motd_text = str(motd)
        motd_text = (motd_text or "")[:180]
        return {
            "online": True,
            "version": getattr(status.version, "name", "?"),
            "players": status.players.online,
            "max_players": status.players.max,
            "motd": motd_text,
        }
    except ImportError:
        return _query_minecraft_fallback(host, port)
    except Exception:
        return {"online": False}


class ServerLinksView(discord.ui.View):
    """Кнопки Steam Connect только для Source; Minecraft — IP в embed."""

    def __init__(self, servers: list[MonitoredServer]):
        super().__init__(timeout=None)
        for s in servers:
            if s.game == "source" and s.steam_url:
                label = f"Steam • {s.name}"[:80]
                self.add_item(
                    discord.ui.Button(
                        label=label,
                        style=discord.ButtonStyle.link,
                        url=s.steam_url,
                    )
                )


class CSMonitor(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = JSONHandler("data/server_monitor.json")
        self._last_refresh_ts: dict[int, float] = {}

    def _guild_cfg(self, guild_id: int) -> dict[str, Any]:
        gid = str(guild_id)
        raw = self.db.get(gid, {})
        return _normalize_guild_cfg(raw)

    def _save_guild_cfg(self, guild_id: int, cfg: dict[str, Any]) -> None:
        self.db.set(str(guild_id), cfg)

    def _servers(self, guild_id: int) -> list[MonitoredServer]:
        cfg = self._guild_cfg(guild_id)
        out: list[MonitoredServer] = []
        for row in cfg.get("servers", []):
            if not isinstance(row, dict):
                continue
            try:
                out.append(
                    MonitoredServer(
                        sid=str(row.get("id", "")),
                        name=str(row.get("name", "Сервер")),
                        game=str(row.get("game", "source")),
                        host=str(row.get("host", "127.0.0.1")),
                        port=int(row.get("port", 27015)),
                    )
                )
            except (TypeError, ValueError):
                continue
        return out

    def _set_servers(self, guild_id: int, servers: list[MonitoredServer]) -> None:
        cfg = self._guild_cfg(guild_id)
        cfg["servers"] = [
            {"id": s.sid, "name": s.name, "game": s.game, "host": s.host, "port": s.port} for s in servers
        ]
        self._save_guild_cfg(guild_id, cfg)

    async def _query_source(self, host: str, port: int) -> dict[str, Any]:
        return await asyncio.to_thread(_query_source_sync, host, port)

    async def _query_minecraft(self, host: str, port: int) -> dict[str, Any]:
        return await asyncio.to_thread(_query_minecraft_sync, host, port)

    async def _query(self, server: MonitoredServer) -> dict[str, Any]:
        if server.game == "minecraft":
            return await self._query_minecraft(server.host, server.port)
        return await self._query_source(server.host, server.port)

    async def build_embed(self, guild_id: int) -> discord.Embed:
        servers = self._servers(guild_id)
        embed = discord.Embed(
            title="🎮 Игровые серверы",
            description="Статус обновляется при вызове команды или **Обновить панель**.\n"
            "• **CS / Source** — запрос по UDP (A2S).\n"
            "• **Minecraft Java** — статус через Server List Ping.",
            color=BRAND,
        )
        if not servers:
            embed.add_field(
                name="Список пуст",
                value="Администраторы могут добавить серверы: `/server_add`",
                inline=False,
            )
            return embed

        for s in servers:
            info = await self._query(s)
            kind = "🟫 Source (CS)" if s.game == "source" else "⛏️ Minecraft"
            if s.game == "source" and info.get("online"):
                status = "🟢 Онлайн"
                body = (
                    f"{kind}\n"
                    f"**Адрес:** `{s.address}`\n"
                    f"**Имя:** {info.get('name', '—')}\n"
                    f"**Карта:** `{info.get('map', '—')}`\n"
                    f"**Игроки:** `{info.get('players', 0)}/{info.get('max_players', 0)}`\n"
                    f"```connect {s.address}```"
                )
            elif s.game == "minecraft" and info.get("online"):
                status = "🟢 Онлайн"
                body = (
                    f"{kind}\n"
                    f"**Адрес:** `{s.address}`\n"
                    f"**Версия:** `{info.get('version', '?')}`\n"
                    f"**Игроки:** `{info.get('players', 0)}/{info.get('max_players', 0)}`\n"
                )
                if info.get("motd"):
                    body += f"**MOTD:** {info['motd']}\n"
                body += f"```{s.address}```"
            else:
                status = "🔴 Недоступен"
                body = (
                    f"{kind}\n"
                    f"**Адрес:** `{s.address}`\n"
                    "Сервер не ответил на запрос (оффлайн, неверный порт или не Java Edition)."
                )
            embed.add_field(name=f"{status} • {s.name}", value=body, inline=False)

        embed.set_footer(text="DS • мониторинг")
        return embed

    @app_commands.command(name="servers", description="Показать статус игровых серверов (CS / Minecraft)")
    async def servers(self, interaction: discord.Interaction):
        embed = await self.build_embed(interaction.guild.id)
        srv = self._servers(interaction.guild.id)
        view = ServerLinksView([s for s in srv if s.game == "source"]) if srv else None
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="server_add", description="Добавить сервер в мониторинг (для админов)")
    @app_commands.describe(
        name="Отображаемое имя",
        game="Тип сервера",
        host="IP или домен",
        port="Порт (по умолчанию: 27015 / 25565)",
    )
    @app_commands.choices(
        game=[
            app_commands.Choice(name="CS / Source (Steam)", value="source"),
            app_commands.Choice(name="Minecraft Java", value="minecraft"),
        ]
    )
    @app_commands.default_permissions(manage_guild=True)
    async def server_add(
        self,
        interaction: discord.Interaction,
        name: app_commands.Range[str, 2, 40],
        game: str,
        host: str,
        port: int | None = None,
    ):
        g = game
        host = host.strip()
        if not host:
            await interaction.response.send_message("❌ Укажите host.", ephemeral=True)
            return
        p = port
        if p is None:
            p = 25565 if g == "minecraft" else 27015
        if p < 1 or p > 65535:
            await interaction.response.send_message("❌ Порт 1–65535.", ephemeral=True)
            return

        servers = self._servers(interaction.guild.id)
        sid = str(uuid.uuid4())[:8]
        servers.append(MonitoredServer(sid=sid, name=name.strip(), game=g, host=host, port=p))
        self._set_servers(interaction.guild.id, servers)
        await interaction.response.send_message(
            f"✅ Сервер **{name}** добавлен (`{g}`, `{host}:{p}`). Используйте `/servers`.",
            ephemeral=True,
        )

    @app_commands.command(name="server_remove", description="Удалить сервер из списка по номеру")
    @app_commands.default_permissions(manage_guild=True)
    async def server_remove(self, interaction: discord.Interaction, index: app_commands.Range[int, 1, 50]):
        servers = self._servers(interaction.guild.id)
        if index > len(servers):
            await interaction.response.send_message("❌ Нет сервера с таким номером. Смотрите `/server_list`.", ephemeral=True)
            return
        removed = servers.pop(index - 1)
        self._set_servers(interaction.guild.id, servers)
        await interaction.response.send_message(f"🗑️ Удалено: **{removed.name}** (`{removed.address}`)", ephemeral=True)

    @app_commands.command(name="server_edit", description="Изменить имя, host или порт")
    @app_commands.default_permissions(manage_guild=True)
    async def server_edit(
        self,
        interaction: discord.Interaction,
        index: app_commands.Range[int, 1, 50],
        name: str | None = None,
        host: str | None = None,
        port: int | None = None,
    ):
        servers = self._servers(interaction.guild.id)
        if index > len(servers):
            await interaction.response.send_message("❌ Неверный номер.", ephemeral=True)
            return
        s = servers[index - 1]
        if name is None and host is None and port is None:
            await interaction.response.send_message("❌ Укажите новое имя, host или порт.", ephemeral=True)
            return
        if name is not None:
            s = MonitoredServer(sid=s.sid, name=name.strip()[:40], game=s.game, host=s.host, port=s.port)
        if host is not None:
            h = host.strip()
            if h:
                s = MonitoredServer(sid=s.sid, name=s.name, game=s.game, host=h, port=s.port)
        if port is not None:
            if port < 1 or port > 65535:
                await interaction.response.send_message("❌ Порт 1–65535.", ephemeral=True)
                return
            s = MonitoredServer(sid=s.sid, name=s.name, game=s.game, host=s.host, port=port)
        servers[index - 1] = s
        self._set_servers(interaction.guild.id, servers)
        await interaction.response.send_message(f"✅ Обновлено: **{s.name}** → `{s.address}`", ephemeral=True)

    @app_commands.command(name="server_list", description="Список серверов с номерами (для удаления/редактирования)")
    @app_commands.default_permissions(manage_guild=True)
    async def server_list(self, interaction: discord.Interaction):
        servers = self._servers(interaction.guild.id)
        if not servers:
            await interaction.response.send_message("📭 Список пуст. `/server_add`", ephemeral=True)
            return
        lines = []
        for i, s in enumerate(servers, start=1):
            kind = "CS/Source" if s.game == "source" else "Minecraft"
            lines.append(f"`{i}.` **{s.name}** — {kind} — `{s.address}`")
        embed = discord.Embed(title="📋 Мониторинг — список", description="\n".join(lines), color=BRAND)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="servers_panel_setup", description="Закрепить панель мониторинга в канале")
    @app_commands.default_permissions(manage_guild=True)
    async def servers_panel_setup(self, interaction: discord.Interaction, channel: discord.TextChannel | None = None):
        target = channel or interaction.channel
        if not isinstance(target, discord.TextChannel):
            await interaction.response.send_message("❌ Укажите текстовый канал", ephemeral=True)
            return
        embed = await self.build_embed(interaction.guild.id)
        srv = self._servers(interaction.guild.id)
        view = ServerLinksView([s for s in srv if s.game == "source"]) if srv else None
        message = await target.send(embed=embed, view=view)
        cfg = self._guild_cfg(interaction.guild.id)
        cfg["panel"] = {"channel_id": target.id, "message_id": message.id}
        self._save_guild_cfg(interaction.guild.id, cfg)
        await interaction.response.send_message(f"✅ Панель отправлена в {target.mention}", ephemeral=True)

    @app_commands.command(name="servers_refresh", description="Обновить закреплённую панель мониторинга")
    @app_commands.default_permissions(manage_guild=True)
    async def servers_refresh(self, interaction: discord.Interaction):
        now = asyncio.get_running_loop().time()
        last = self._last_refresh_ts.get(interaction.guild.id, 0.0)
        if now - last < 10:
            wait_for = int(10 - (now - last))
            await interaction.response.send_message(
                f"⏳ Слишком частое обновление панели. Повторите через {wait_for} сек.",
                ephemeral=True,
            )
            return
        cfg = self._guild_cfg(interaction.guild.id)
        panel = cfg.get("panel") or {}
        channel_id = panel.get("channel_id")
        message_id = panel.get("message_id")
        if not channel_id or not message_id:
            await interaction.response.send_message("❌ Сначала `/servers_panel_setup`", ephemeral=True)
            return
        channel = interaction.guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("❌ Канал не найден", ephemeral=True)
            return
        try:
            message = await channel.fetch_message(message_id)
        except discord.NotFound:
            await interaction.response.send_message("❌ Сообщение панели не найдено", ephemeral=True)
            return
        embed = await self.build_embed(interaction.guild.id)
        srv = self._servers(interaction.guild.id)
        view = ServerLinksView([s for s in srv if s.game == "source"]) if srv else None
        await message.edit(embed=embed, view=view)
        self._last_refresh_ts[interaction.guild.id] = now
        await interaction.response.send_message("✅ Панель обновлена", ephemeral=True)


async def setup(bot: commands.Bot):
    from utils import target_guilds

    guilds = target_guilds()
    if guilds is None:
        await bot.add_cog(CSMonitor(bot))
    else:
        await bot.add_cog(CSMonitor(bot), guilds=guilds)
