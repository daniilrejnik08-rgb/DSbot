"""Forms / Applications — порт Discord-Form-Bot (Rage-Gaming):
модальные анкеты, панель подачи, accept/reject, роли, DM."""
from __future__ import annotations

import time
import uuid
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from utils import JSONHandler

try:
    from utils.theme import BRAND, SUCCESS, DANGER, GOLD
except Exception:
    BRAND = discord.Color.blurple()
    SUCCESS = discord.Color.green()
    DANGER = discord.Color.red()
    GOLD = discord.Color.gold()

# Discord modal max 5 TextInputs
_MAX_FIELDS = 5

_DEFAULT_QUESTIONS = [
    {
        "key": "q1",
        "label": "Как вас зовут / ник?",
        "style": "short",
        "placeholder": "Ваш ответ",
        "required": True,
        "max_length": 100,
    },
    {
        "key": "q2",
        "label": "Возраст",
        "style": "short",
        "placeholder": "Например: 18",
        "required": True,
        "max_length": 10,
    },
    {
        "key": "q3",
        "label": "Почему хотите вступить?",
        "style": "paragraph",
        "placeholder": "Расскажите кратко…",
        "required": True,
        "max_length": 1000,
    },
    {
        "key": "q4",
        "label": "Опыт (игры / Discord)",
        "style": "paragraph",
        "placeholder": "Необязательно",
        "required": False,
        "max_length": 1000,
    },
]


def _style(name: str) -> discord.TextStyle:
    return discord.TextStyle.paragraph if str(name).lower() in {"paragraph", "long", "2"} else discord.TextStyle.short


class FormModal(discord.ui.Modal):
    def __init__(self, cog: "Forms", guild_id: int, form_id: str, questions: list[dict]):
        cfg_title = "Анкета"
        data = cog._guild(guild_id)
        form = (data.get("forms") or {}).get(form_id) or {}
        cfg_title = str(form.get("modal_title") or form.get("name") or "Анкета")[:45]
        super().__init__(title=cfg_title)
        self.cog = cog
        self.guild_id = guild_id
        self.form_id = form_id
        self.questions = questions[:_MAX_FIELDS]
        self._inputs: list[discord.ui.TextInput] = []
        for q in self.questions:
            ti = discord.ui.TextInput(
                label=str(q.get("label") or q.get("key"))[:45],
                style=_style(q.get("style", "short")),
                placeholder=str(q.get("placeholder") or "")[:100] or None,
                required=bool(q.get("required", True)),
                max_length=min(int(q.get("max_length") or 400), 1000),
                custom_id=str(q.get("key") or f"q{len(self._inputs)}"),
            )
            self._inputs.append(ti)
            self.add_item(ti)

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog._handle_submit(
            interaction,
            self.form_id,
            self.questions,
            {ti.custom_id: str(ti.value) for ti in self._inputs},
        )


class FormApplyView(discord.ui.View):
    """Persistent: custom_id encodes form_id."""

    def __init__(self, cog: "Forms", form_id: str = "default"):
        super().__init__(timeout=None)
        self.cog = cog
        self.form_id = form_id
        # dynamic custom_id for multi-form
        btn = discord.ui.Button(
            label="Заполнить анкету",
            emoji="📝",
            style=discord.ButtonStyle.primary,
            custom_id=f"form:apply:{form_id}",
        )
        btn.callback = self._apply  # type: ignore
        self.add_item(btn)

    async def _apply(self, interaction: discord.Interaction):
        form_id = "default"
        if interaction.data and isinstance(interaction.data, dict):
            cid = str(interaction.data.get("custom_id") or "")
            if cid.startswith("form:apply:"):
                form_id = cid.split("form:apply:", 1)[-1] or "default"
        data = self.cog._guild(interaction.guild_id)
        form = (data.get("forms") or {}).get(form_id)
        if not form or not form.get("enabled", True):
            await interaction.response.send_message("❌ Анкета отключена или не найдена.", ephemeral=True)
            return
        # one pending per user per form
        for sub in (data.get("submissions") or {}).values():
            if (
                sub.get("form_id") == form_id
                and sub.get("user_id") == interaction.user.id
                and sub.get("status") == "pending"
            ):
                await interaction.response.send_message(
                    "❌ У вас уже есть **ожидающая** заявка по этой анкете.",
                    ephemeral=True,
                )
                return
        questions = form.get("questions") or _DEFAULT_QUESTIONS
        modal = FormModal(self.cog, interaction.guild_id, form_id, questions)
        await interaction.response.send_modal(modal)


class FormReviewView(discord.ui.View):
    def __init__(self, cog: "Forms", submission_id: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.submission_id = submission_id
        accept = discord.ui.Button(
            label="Принять",
            emoji="✅",
            style=discord.ButtonStyle.success,
            custom_id=f"form:accept:{submission_id}",
        )
        reject = discord.ui.Button(
            label="Отклонить",
            emoji="❌",
            style=discord.ButtonStyle.danger,
            custom_id=f"form:reject:{submission_id}",
        )
        accept.callback = self._accept  # type: ignore
        reject.callback = self._reject  # type: ignore
        self.add_item(accept)
        self.add_item(reject)

    async def _accept(self, interaction: discord.Interaction):
        sid = self._sid(interaction)
        await self.cog._review(interaction, sid, accept=True)

    async def _reject(self, interaction: discord.Interaction):
        sid = self._sid(interaction)
        await self.cog._review(interaction, sid, accept=False)

    @staticmethod
    def _sid(interaction: discord.Interaction) -> str:
        if interaction.data and isinstance(interaction.data, dict):
            cid = str(interaction.data.get("custom_id") or "")
            if ":" in cid:
                return cid.split(":")[-1]
        return ""


class Forms(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = JSONHandler("data/forms.json")
        # register persistent views for known forms + generic router via on_interaction fallback
        self.bot.add_view(FormApplyView(self, "default"))
        # review views registered dynamically; also handle via listener

    def _guild(self, guild_id: int) -> dict:
        key = str(guild_id)
        data = self.db.get(key, {}) or {}
        data.setdefault("forms", {})
        data.setdefault("submissions", {})
        data.setdefault("review_channel_id", None)
        data.setdefault("log_channel_id", None)
        return data

    def _save(self, guild_id: int, data: dict):
        self.db.set(str(guild_id), data)

    def _ensure_default_form(self, data: dict) -> dict:
        forms = data.setdefault("forms", {})
        if "default" not in forms:
            forms["default"] = {
                "name": "Заявка",
                "modal_title": "Заявка на вступление",
                "enabled": True,
                "questions": list(_DEFAULT_QUESTIONS),
                "accept_role_ids": [],
                "panel_title": "📝 Подать заявку",
                "panel_description": (
                    "Нажмите кнопку ниже и заполните анкету.\n"
                    "Администрация рассмотрит заявку и ответит в ЛС."
                ),
                "panel_color": None,
            }
        return forms["default"]

    async def _handle_submit(
        self,
        interaction: discord.Interaction,
        form_id: str,
        questions: list[dict],
        answers: dict[str, str],
    ):
        data = self._guild(interaction.guild_id)
        form = (data.get("forms") or {}).get(form_id) or {}
        sid = uuid.uuid4().hex[:12]
        sub = {
            "id": sid,
            "form_id": form_id,
            "user_id": interaction.user.id,
            "username": str(interaction.user),
            "answers": answers,
            "status": "pending",
            "created_at": int(time.time()),
            "reviewer_id": None,
        }
        data.setdefault("submissions", {})[sid] = sub
        self._save(interaction.guild_id, data)

        # build review embed
        emb = discord.Embed(
            title=f"📥 Новая заявка — {form.get('name') or form_id}",
            description=f"От: {interaction.user.mention} (`{interaction.user.id}`)",
            color=GOLD,
            timestamp=discord.utils.utcnow(),
        )
        label_map = {q.get("key"): q.get("label") for q in questions}
        for key, val in answers.items():
            title = str(label_map.get(key) or key)[:256]
            emb.add_field(name=title, value=(val or "—")[:1024], inline=False)
        emb.set_footer(text=f"submission:{sid}")
        emb.set_thumbnail(url=interaction.user.display_avatar.url)

        view = FormReviewView(self, sid)
        self.bot.add_view(view)

        review_id = data.get("review_channel_id")
        sent = False
        if review_id:
            ch = interaction.guild.get_channel(int(review_id))
            if isinstance(ch, discord.TextChannel):
                try:
                    await ch.send(embed=emb, view=view)
                    sent = True
                except Exception:
                    pass
        if not sent:
            # fallback: reply ephemeral notice + try current channel if admin
            try:
                if interaction.channel and isinstance(interaction.channel, discord.TextChannel):
                    await interaction.channel.send(embed=emb, view=view)
                    sent = True
            except Exception:
                pass

        await interaction.response.send_message(
            embed=discord.Embed(
                description=(
                    "✅ Анкета **отправлена** на рассмотрение.\n"
                    "Результат придёт в личные сообщения (если открыты ЛС)."
                ),
                color=SUCCESS,
            ),
            ephemeral=True,
        )

    async def _review(
        self, interaction: discord.Interaction, submission_id: str, *, accept: bool
    ):
        if not interaction.user.guild_permissions.manage_guild and not interaction.user.guild_permissions.manage_roles:
            await interaction.response.send_message("❌ Нужны права Manage Server/Roles", ephemeral=True)
            return

        data = self._guild(interaction.guild_id)
        sub = (data.get("submissions") or {}).get(submission_id)
        if not sub:
            await interaction.response.send_message("❌ Заявка не найдена", ephemeral=True)
            return
        if sub.get("status") != "pending":
            await interaction.response.send_message(
                f"❌ Уже обработана: **{sub.get('status')}**", ephemeral=True
            )
            return

        form = (data.get("forms") or {}).get(sub.get("form_id") or "default") or {}
        member = interaction.guild.get_member(int(sub["user_id"]))
        sub["status"] = "accepted" if accept else "rejected"
        sub["reviewer_id"] = interaction.user.id
        sub["reviewed_at"] = int(time.time())
        data["submissions"][submission_id] = sub
        self._save(interaction.guild_id, data)

        if accept and member:
            for rid in form.get("accept_role_ids") or []:
                role = interaction.guild.get_role(int(rid))
                if role:
                    try:
                        await member.add_roles(role, reason=f"Form accepted by {interaction.user}")
                    except Exception:
                        pass

        # update original message
        color = SUCCESS if accept else DANGER
        status_txt = "✅ ПРИНЯТА" if accept else "❌ ОТКЛОНЕНА"
        try:
            if interaction.message and interaction.message.embeds:
                emb = interaction.message.embeds[0]
                emb.color = color
                emb.add_field(
                    name="Статус",
                    value=f"{status_txt} · {interaction.user.mention}",
                    inline=False,
                )
                await interaction.message.edit(embed=emb, view=None)
            else:
                await interaction.message.edit(view=None)
        except Exception:
            pass

        await interaction.response.send_message(
            f"{status_txt} — <@{sub['user_id']}>", ephemeral=True
        )

        # DM user
        user = member or self.bot.get_user(int(sub["user_id"]))
        if user:
            try:
                if accept:
                    dm = discord.Embed(
                        title="✅ Заявка принята",
                        description=(
                            f"Ваша анкета **{form.get('name') or sub.get('form_id')}** "
                            f"на **{interaction.guild.name}** принята.\n"
                            f"Модератор: {interaction.user.mention}"
                        ),
                        color=SUCCESS,
                    )
                else:
                    dm = discord.Embed(
                        title="❌ Заявка отклонена",
                        description=(
                            f"Ваша анкета **{form.get('name') or sub.get('form_id')}** "
                            f"на **{interaction.guild.name}** отклонена.\n"
                            f"Модератор: {interaction.user.mention}"
                        ),
                        color=DANGER,
                    )
                await user.send(embed=dm)
            except Exception:
                pass

        # log channel
        log_id = data.get("log_channel_id") or data.get("review_channel_id")
        if log_id:
            ch = interaction.guild.get_channel(int(log_id))
            if isinstance(ch, discord.TextChannel) and ch.id != getattr(interaction.channel, "id", None):
                try:
                    await ch.send(
                        embed=discord.Embed(
                            description=(
                                f"{status_txt} заявка `{submission_id}` "
                                f"от <@{sub['user_id']}> · {interaction.user.mention}"
                            ),
                            color=color,
                        )
                    )
                except Exception:
                    pass

    # ── slash commands ───────────────────────────────────────────────

    @app_commands.command(name="form_setup", description="Настроить систему анкет (канал проверки, роли)")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(
        review_channel="Куда слать заявки на проверку",
        accept_role="Роль при принятии (можно добавить несколько через повтор)",
        log_channel="Опционально: лог решений",
        form_id="ID анкеты (по умолчанию default)",
    )
    async def form_setup(
        self,
        interaction: discord.Interaction,
        review_channel: discord.TextChannel,
        accept_role: discord.Role | None = None,
        log_channel: discord.TextChannel | None = None,
        form_id: str = "default",
    ):
        data = self._guild(interaction.guild_id)
        form = self._ensure_default_form(data)
        if form_id != "default":
            data.setdefault("forms", {}).setdefault(
                form_id,
                {
                    "name": form_id,
                    "modal_title": form_id[:45],
                    "enabled": True,
                    "questions": list(_DEFAULT_QUESTIONS),
                    "accept_role_ids": [],
                    "panel_title": f"📝 {form_id}",
                    "panel_description": "Нажмите кнопку и заполните анкету.",
                },
            )
            form = data["forms"][form_id]

        data["review_channel_id"] = review_channel.id
        if log_channel:
            data["log_channel_id"] = log_channel.id
        if accept_role:
            ids = list(form.get("accept_role_ids") or [])
            if accept_role.id not in ids:
                ids.append(accept_role.id)
            form["accept_role_ids"] = ids
            data["forms"][form_id] = form
        self._save(interaction.guild_id, data)

        roles = ", ".join(f"<@&{r}>" for r in (form.get("accept_role_ids") or [])) or "—"
        await interaction.response.send_message(
            embed=discord.Embed(
                title="✅ Forms настроены",
                description=(
                    f"Анкета: `{form_id}`\n"
                    f"Проверка: {review_channel.mention}\n"
                    f"Роли при accept: {roles}\n\n"
                    f"Далее: `/form_panel` — выложить кнопку\n"
                    f"`/form_questions` — посмотреть вопросы"
                ),
                color=SUCCESS,
            ),
            ephemeral=True,
        )

    @app_commands.command(name="form_panel", description="Выложить панель с кнопкой анкеты")
    @app_commands.default_permissions(manage_guild=True)
    async def form_panel(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel | None = None,
        form_id: str = "default",
    ):
        data = self._guild(interaction.guild_id)
        form = (data.get("forms") or {}).get(form_id)
        if not form:
            self._ensure_default_form(data)
            form = data["forms"]["default"]
            form_id = "default"
            self._save(interaction.guild_id, data)

        target = channel or interaction.channel
        if not isinstance(target, discord.TextChannel):
            await interaction.response.send_message("❌ Укажите текстовый канал", ephemeral=True)
            return

        color = BRAND
        raw = form.get("panel_color")
        if raw and isinstance(raw, str) and len(raw) == 6:
            try:
                color = discord.Color(int(raw, 16))
            except ValueError:
                pass

        emb = discord.Embed(
            title=form.get("panel_title") or "📝 Подать заявку",
            description=form.get("panel_description")
            or "Нажмите кнопку ниже и заполните анкету.",
            color=color,
        )
        emb.set_footer(text=f"form:{form_id}")
        view = FormApplyView(self, form_id)
        self.bot.add_view(view)
        await target.send(embed=emb, view=view)
        await interaction.response.send_message(
            f"✅ Панель отправлена в {target.mention}", ephemeral=True
        )

    @app_commands.command(name="form_questions", description="Показать вопросы анкеты")
    @app_commands.default_permissions(manage_guild=True)
    async def form_questions(self, interaction: discord.Interaction, form_id: str = "default"):
        data = self._guild(interaction.guild_id)
        form = (data.get("forms") or {}).get(form_id)
        if not form:
            await interaction.response.send_message("❌ Анкета не найдена", ephemeral=True)
            return
        lines = []
        for i, q in enumerate(form.get("questions") or [], 1):
            req = "*" if q.get("required", True) else ""
            lines.append(
                f"**{i}. {q.get('label')}**{req} `{q.get('key')}` "
                f"({q.get('style', 'short')})"
            )
        emb = discord.Embed(
            title=f"Вопросы — {form.get('name') or form_id}",
            description="\n".join(lines) or "Нет вопросов",
            color=BRAND,
        )
        emb.set_footer(text="Правка questions — через data/forms.json или /form_set_question")
        await interaction.response.send_message(embed=emb, ephemeral=True)

    @app_commands.command(
        name="form_set_question",
        description="Задать/заменить вопрос анкеты (слот 1–5)",
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(
        slot="Номер вопроса 1–5",
        label="Текст вопроса",
        style="short или paragraph",
        required="Обязательный?",
        placeholder="Подсказка в поле",
    )
    async def form_set_question(
        self,
        interaction: discord.Interaction,
        slot: app_commands.Range[int, 1, 5],
        label: app_commands.Range[str, 1, 45],
        style: str = "short",
        required: bool = True,
        placeholder: str = "",
        form_id: str = "default",
    ):
        if style.lower() not in {"short", "paragraph", "long"}:
            await interaction.response.send_message(
                "❌ style: `short` или `paragraph`", ephemeral=True
            )
            return
        data = self._guild(interaction.guild_id)
        form = (data.get("forms") or {}).get(form_id)
        if not form:
            self._ensure_default_form(data)
            form = data["forms"]["default"]
            form_id = "default"
        qs = list(form.get("questions") or [])
        while len(qs) < slot:
            qs.append(
                {
                    "key": f"q{len(qs)+1}",
                    "label": f"Вопрос {len(qs)+1}",
                    "style": "short",
                    "required": False,
                    "placeholder": "",
                    "max_length": 200,
                }
            )
        qs[slot - 1] = {
            "key": f"q{slot}",
            "label": label,
            "style": "paragraph" if style.lower() in {"paragraph", "long"} else "short",
            "required": required,
            "placeholder": placeholder[:100],
            "max_length": 1000 if style.lower() in {"paragraph", "long"} else 200,
        }
        form["questions"] = qs[:_MAX_FIELDS]
        data["forms"][form_id] = form
        self._save(interaction.guild_id, data)
        await interaction.response.send_message(
            f"✅ Вопрос **{slot}**: {label}", ephemeral=True
        )

    @app_commands.command(name="form_list", description="Список заявок (pending)")
    @app_commands.default_permissions(manage_guild=True)
    async def form_list(self, interaction: discord.Interaction, form_id: str | None = None):
        data = self._guild(interaction.guild_id)
        lines = []
        for sid, sub in (data.get("submissions") or {}).items():
            if sub.get("status") != "pending":
                continue
            if form_id and sub.get("form_id") != form_id:
                continue
            lines.append(f"`{sid}` · <@{sub.get('user_id')}> · {sub.get('form_id')}")
        emb = discord.Embed(
            title="⏳ Ожидают рассмотрения",
            description="\n".join(lines[:30]) or "Пусто",
            color=GOLD,
        )
        await interaction.response.send_message(embed=emb, ephemeral=True)

    @app_commands.command(name="form_accept", description="Принять заявку по ID")
    @app_commands.default_permissions(manage_guild=True)
    async def form_accept(self, interaction: discord.Interaction, submission_id: str):
        await self._review(interaction, submission_id.strip(), accept=True)

    @app_commands.command(name="form_reject", description="Отклонить заявку по ID")
    @app_commands.default_permissions(manage_guild=True)
    async def form_reject(self, interaction: discord.Interaction, submission_id: str):
        await self._review(interaction, submission_id.strip(), accept=False)

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        """Подхват persistent кнопок form:apply / form:accept / form:reject после рестарта."""
        if interaction.type is not discord.InteractionType.component:
            return
        if not interaction.data or not isinstance(interaction.data, dict):
            return
        cid = str(interaction.data.get("custom_id") or "")
        if not cid.startswith("form:"):
            return
        # If the view already handled it, response is done — skip
        if interaction.response.is_done():
            return
        parts = cid.split(":")
        if len(parts) < 3:
            return
        action, payload = parts[1], parts[2]
        if action == "apply":
            # open modal for form_id=payload
            data = self._guild(interaction.guild_id)
            form = (data.get("forms") or {}).get(payload)
            if not form:
                await interaction.response.send_message("❌ Анкета не найдена", ephemeral=True)
                return
            for sub in (data.get("submissions") or {}).values():
                if (
                    sub.get("form_id") == payload
                    and sub.get("user_id") == interaction.user.id
                    and sub.get("status") == "pending"
                ):
                    await interaction.response.send_message(
                        "❌ У вас уже есть ожидающая заявка.", ephemeral=True
                    )
                    return
            questions = form.get("questions") or _DEFAULT_QUESTIONS
            await interaction.response.send_modal(
                FormModal(self, interaction.guild_id, payload, questions)
            )
        elif action in {"accept", "reject"}:
            await self._review(interaction, payload, accept=(action == "accept"))


async def setup(bot: commands.Bot):
    await bot.add_cog(Forms(bot))
