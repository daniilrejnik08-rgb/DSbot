import logging
import os

import discord
from aiohttp import web
from discord.ext import commands

log = logging.getLogger(__name__)


class SiteBridge(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._runner = None
        self._site = None
        self._token = (os.getenv("SITE_BRIDGE_TOKEN") or "").strip()
        self._host = (os.getenv("SITE_BRIDGE_HOST") or "0.0.0.0").strip()
        self._port = int((os.getenv("SITE_BRIDGE_PORT") or "8099").strip())
        self._enabled = (os.getenv("SITE_BRIDGE_ENABLED") or "0").strip().lower() in {"1", "true", "yes", "on"}

    async def cog_load(self):
        if not self._enabled:
            log.info("site_bridge: disabled (set SITE_BRIDGE_ENABLED=1)")
            return
        if not self._token:
            log.warning("site_bridge: SITE_BRIDGE_TOKEN is empty, bridge not started")
            return

        app = web.Application()
        app.router.add_post("/site/call-admin/{token}", self.handle_call_admin)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self._host, self._port)
        await self._site.start()
        log.info("site_bridge: started on %s:%s", self._host, self._port)

    async def cog_unload(self):
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
            self._site = None

    async def _resolve_channel(self):
        raw = (os.getenv("SITE_CALL_CHANNEL_ID") or "").strip()
        if not raw.isdigit():
            return None
        cid = int(raw)
        ch = self.bot.get_channel(cid)
        if ch is not None:
            return ch
        try:
            return await self.bot.fetch_channel(cid)
        except Exception:
            return None

    async def handle_call_admin(self, request: web.Request):
        if request.match_info.get("token", "") != self._token:
            return web.json_response({"ok": False, "error": "forbidden"}, status=403)
        try:
            payload = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid_json"}, status=400)

        channel = await self._resolve_channel()
        if channel is None:
            return web.json_response({"ok": False, "error": "channel_not_found"}, status=500)

        try:
            content = payload.get("content")
            embeds = payload.get("embeds") or []
            ds_embeds = []
            for item in embeds[:10]:
                if isinstance(item, dict):
                    ds_embeds.append(discord.Embed.from_dict(item))
            if not content and not ds_embeds:
                content = "Новый вызов администрации (пустой payload)"
            await channel.send(content=content, embeds=ds_embeds)
            return web.json_response({"ok": True})
        except Exception as e:
            log.exception("site_bridge send error: %s", e)
            return web.json_response({"ok": False, "error": "send_failed"}, status=500)


async def setup(bot: commands.Bot):
    from utils import target_guilds

    guilds = target_guilds()
    if guilds is None:
        await bot.add_cog(SiteBridge(bot))
    else:
        await bot.add_cog(SiteBridge(bot), guilds=guilds)
