import os
import re
import json
import uuid
import random
import calendar
import asyncio
import aiohttp
import discord
from datetime import datetime, timedelta, time as dt_time
from zoneinfo import ZoneInfo
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv
load_dotenv()

# ================================================================
#                        CONFIGURATION
# ================================================================
PREFIX = "+"

STAFF_ROLE_NAME = "Ping staff"          # Nom exact du rôle staff sur ton serveur
STATS_CATEGORY_NAME = "🧽 SERVEUR STATS"
STATS_UPDATE_INTERVAL_MINUTES = 10      # Discord limite les renommages de salons (~2 / 10 min)
CONFIG_FILE = "config.json"             # Stockage persistant des rôles autorisés à valider
DEV_GUILD_ID = 1537139988448153640      # ID de ton serveur, pour une synchro instantanée des slash commands
 
# ---- Élu de la semaine ----
ELU_ROLE_NAME = "👑 Élu de la semaine"
ELU_GIF_URL = "https://media1.tenor.com/m/9BEFbzse_iUAAAAC/hunter-x-hunter-vacuum.gif"
PARIS_TZ = ZoneInfo("Europe/Paris")

# ---- Tickets ----
TICKETS_CATEGORY_NAME = "🎫 TICKETS"     # Catégorie par défaut où sont créés les salons de tickets

# ---- TikTok ----
TIKTOK_USERNAME = "7vkp2"                # Compte TikTok suivi (https://www.tiktok.com/@7vkp2)
TIKTOK_CHECK_INTERVAL_MINUTES = 10       # Fréquence de vérification des nouvelles vidéos
# ================================================================
 
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.presences = True
 
bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)
 
 
def is_staff(member: discord.Member) -> bool:
    """Vérifie si un membre est staff (rôle 'Staff' ou permission administrateur)."""
    if member.guild_permissions.administrator:
        return True
    return any(role.name == STAFF_ROLE_NAME for role in member.roles)
 
 
# ---------------- Config persistante (rôles de validation) ----------------
 
def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}
 
 
def save_config(data: dict) -> None:
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
 
 
config = load_config()
 
 
def get_validator_roles(guild_id: int, categorie: str) -> list:
    return config.get(str(guild_id), {}).get(categorie, [])
 
 
def add_validator_role(guild_id: int, categorie: str, role_id: int) -> None:
    guild_conf = config.setdefault(str(guild_id), {})
    roles = guild_conf.setdefault(categorie, [])
    if role_id not in roles:
        roles.append(role_id)
    save_config(config)
 
 
# ================================================================
#                          +cmds
# ================================================================
 
NORMAL_COMMANDS = [
    ("+cmds", "Affiche la liste des commandes disponibles."),
    ("+invite-stats", "Affiche combien de membres tu as invités sur le serveur."),
    ("+concept list", "Affiche la liste des notés du Concept."),
    ("/animal collection", "Affiche les animaux que tu as capturés."),
    ("/animal classement", "Affiche le classement des meilleurs chasseurs d'animaux."),
    ("/pet inventory", "Affiche ton inventaire d'animaux capturés."),
    ("/pet trade [@membre]", "Propose un échange d'animal avec un autre membre."),
    ("/report envoyer [@membre] [raison]", "Signale discrètement un membre au staff."),
]
 
STAFF_COMMANDS = [
    ("+absences", "Ouvre un formulaire pour déclarer une absence."),
    ("+role-react setup", "Crée un message à réactions qui donne des rôles."),
    ("/ticketsetup", "Crée un panneau de tickets personnalisable (staff)."),
    ("/set updatelogs [salon]", "Définit le salon des nouveautés du bot et y publie le changelog (staff)."),
    ("/animal config [salon]", "Active le système d'animaux à capturer dans ce salon (staff)."),
    ("/animal forcespawn", "Force l'apparition immédiate d'un animal (staff)."),
    ("/pet spawn", "Force l'apparition immédiate d'un animal (staff, alias de /animal forcespawn)."),
    ("/admin panel", "Ouvre le panneau d'administration : boost de chance x10, spawn x10 (staff)."),
    ("/maintenance serveur", "Active/désactive le mode maintenance : salons privés sauf staff (propriétaire uniquement)."),
    ("/soutiens", "Configure et affiche le panneau des soutiens du serveur (staff)."),
    ("+concept note @membre", "Notez une personne dans la listes des concepts."),
    ("+concept list reset", "Réinitialise la liste Concept."),
    ("/eludelasemaine", "Affiche les règles de l'Élu de la semaine (staff)."),
    ("/forcerelu", "Force la sélection immédiate de l'Élu de la semaine (staff)."),
    ("/clear [nombre]", "Supprime un nombre de messages dans le salon (staff)."),
    ("+warn @membre <raison>", "Donne un avertissement à un membre."),
    ("+warn list @membre", "Affiche les avertissements d'un membre."),
    ("+mute @membre <durée> [raison]", "Rend un membre muet (ex : 10m, 2h, 1j)."),
    ("+unmute @membre", "Retire le mute d'un membre."),
    ("+add role @membre @role", "Ajoute un rôle à un membre."),
    ("+remove role @membre @role", "Retire un rôle à un membre."),
    ("+lock", "Verrouille le salon : seul le rôle Staff peut y écrire."),
    ("+unlock", "Déverrouille le salon."),
    ("/report config [salon]", "Définit le salon privé où arrivent les signalements (staff)."),
    ("/report historique [@membre]", "Affiche les signalements reçus contre un membre (staff)."),
]


def build_staff_commands_pages() -> list:
    """Découpe STAFF_COMMANDS en 2 pages d'embeds à peu près égales."""
    milieu = (len(STAFF_COMMANDS) + 1) // 2
    tranches = [STAFF_COMMANDS[:milieu], STAFF_COMMANDS[milieu:]]

    pages = []
    for i, items in enumerate(tranches, start=1):
        embed = discord.Embed(title=f"🛠️ Commandes Staff (page {i}/{len(tranches)})", color=discord.Color.red())
        for name, desc in items:
            embed.add_field(name=name, value=desc, inline=False)
        pages.append(embed)
    return pages


class StaffCommandsPaginator(discord.ui.View):
    """Pagination simple (◀️/▶️) pour +cmds staff. Seule la personne ayant
    lancé la commande peut naviguer."""

    def __init__(self, pages: list, author_id: int):
        super().__init__(timeout=120)
        self.pages = pages
        self.index = 0
        self.author_id = author_id
        self.message: discord.Message | None = None
        self._maj_boutons()

    def _maj_boutons(self):
        self.bouton_precedent.disabled = self.index == 0
        self.bouton_suivant.disabled = self.index == len(self.pages) - 1

    @discord.ui.button(label="◀️ Précédent", style=discord.ButtonStyle.secondary)
    async def bouton_precedent(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "❌ Seule la personne ayant utilisé la commande peut changer de page.", ephemeral=True
            )
            return
        self.index = max(0, self.index - 1)
        self._maj_boutons()
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)

    @discord.ui.button(label="Suivant ▶️", style=discord.ButtonStyle.secondary)
    async def bouton_suivant(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "❌ Seule la personne ayant utilisé la commande peut changer de page.", ephemeral=True
            )
            return
        self.index = min(len(self.pages) - 1, self.index + 1)
        self._maj_boutons()
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


@bot.command(name="cmds")
async def cmds_command(ctx: commands.Context, sous_commande: str = None):
    if sous_commande and sous_commande.lower() == "staff":
        if not is_staff(ctx.author):
            await ctx.send("❌ Tu n'as pas la permission de voir les commandes staff.")
            return
        pages = build_staff_commands_pages()
        view = StaffCommandsPaginator(pages, ctx.author.id)
        message = await ctx.send(embed=pages[0], view=view)
        view.message = message
        return

    embed = discord.Embed(title="📜 Liste des commandes", color=discord.Color.blurple())
    for name, desc in NORMAL_COMMANDS:
        embed.add_field(name=name, value=desc, inline=False)
    embed.set_footer(text="Tape +cmds staff si tu es membre du staff pour voir plus de commandes.")
    await ctx.send(embed=embed)
 
 
# ================================================================
#                        +lock / +unlock
# ================================================================

@bot.command(name="lock")
async def lock_command(ctx: commands.Context):
    if not is_staff(ctx.author):
        await ctx.send("❌ Cette commande est réservée au staff.")
        return

    staff_role = discord.utils.get(ctx.guild.roles, name=STAFF_ROLE_NAME)

    overwrite_everyone = ctx.channel.overwrites_for(ctx.guild.default_role)
    overwrite_everyone.send_messages = False

    try:
        await ctx.channel.set_permissions(
            ctx.guild.default_role, overwrite=overwrite_everyone, reason=f"Salon verrouillé par {ctx.author}"
        )
        if staff_role:
            overwrite_staff = ctx.channel.overwrites_for(staff_role)
            overwrite_staff.send_messages = True
            await ctx.channel.set_permissions(
                staff_role, overwrite=overwrite_staff, reason=f"Accès staff maintenu (verrouillage par {ctx.author})"
            )
    except discord.Forbidden:
        await ctx.send("❌ Je n'ai pas la permission de modifier les permissions de ce salon.")
        return

    embed = discord.Embed(
        title="🔒 Salon verrouillé",
        description=f"Seuls les membres avec le rôle **{STAFF_ROLE_NAME}** peuvent désormais écrire ici.",
        color=discord.Color.red(),
    )
    embed.set_footer(text=f"Verrouillé par {ctx.author}")
    await ctx.send(embed=embed)


@bot.command(name="unlock")
async def unlock_command(ctx: commands.Context):
    if not is_staff(ctx.author):
        await ctx.send("❌ Cette commande est réservée au staff.")
        return

    overwrite_everyone = ctx.channel.overwrites_for(ctx.guild.default_role)
    overwrite_everyone.send_messages = None  # retire l'overwrite explicite (retour à l'héritage normal)

    try:
        await ctx.channel.set_permissions(
            ctx.guild.default_role, overwrite=overwrite_everyone, reason=f"Salon déverrouillé par {ctx.author}"
        )
    except discord.Forbidden:
        await ctx.send("❌ Je n'ai pas la permission de modifier les permissions de ce salon.")
        return

    embed = discord.Embed(
        title="🔓 Salon déverrouillé",
        description="Tout le monde peut de nouveau écrire ici.",
        color=discord.Color.green(),
    )
    embed.set_footer(text=f"Déverrouillé par {ctx.author}")
    await ctx.send(embed=embed)
 
 
# ================================================================
#                        +absences
# ================================================================
 
class AbsenceModal(discord.ui.Modal, title="Déclaration d'absence"):
    pseudo = discord.ui.TextInput(label="Pseudo", placeholder="Ton pseudo Discord", max_length=100)
    date = discord.ui.TextInput(label="Date", placeholder="Ex : 20/08/2026", max_length=50)
    raison = discord.ui.TextInput(
        label="Raison",
        style=discord.TextStyle.paragraph,
        placeholder="Explique la raison de ton absence",
        max_length=500,
    )
 
    async def on_submit(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="📋 Nouvelle déclaration d'absence",
            color=discord.Color.orange(),
            timestamp=datetime.utcnow(),
        )
        embed.add_field(name="Pseudo", value=self.pseudo.value, inline=False)
        embed.add_field(name="Date", value=self.date.value, inline=False)
        embed.add_field(name="Raison", value=self.raison.value, inline=False)
        embed.add_field(name="Statut", value="⏳ En attente de validation", inline=False)
        embed.set_footer(text=f"Envoyé par {interaction.user}", icon_url=interaction.user.display_avatar.url)
 
        await interaction.channel.send(embed=embed, view=ValidateAbsenceView(interaction.user.id))
        await interaction.response.send_message("✅ Ton absence a bien été déclarée.", ephemeral=True)
 
 
class AbsenceView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
 
    @discord.ui.button(
        label="📋 Remplir le formulaire",
        style=discord.ButtonStyle.primary,
        custom_id="absence_form_button",
    )
    async def open_form(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AbsenceModal())
 
 
class ValidateAbsenceView(discord.ui.View):
    """Bouton affiché sous chaque déclaration d'absence, réservé aux rôles autorisés."""
 
    def __init__(self, target_user_id: int):
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Button(
                label="✅ Valider l'absence",
                style=discord.ButtonStyle.success,
                custom_id=f"validate_absence:{target_user_id}",
            )
        )
 
 
@bot.listen("on_interaction")
async def on_validate_absence_interaction(interaction: discord.Interaction):
    """Écoute les clics sur le bouton de validation d'absence (survit aux redémarrages)."""
    if interaction.type != discord.InteractionType.component:
        return
    custom_id = interaction.data.get("custom_id", "")
    if not custom_id.startswith("validate_absence:"):
        return
 
    target_user_id = int(custom_id.split(":", 1)[1])
    allowed_role_ids = get_validator_roles(interaction.guild.id, "absences")
 
    member = interaction.user
    if allowed_role_ids:
        authorized = member.guild_permissions.administrator or any(
            role.id in allowed_role_ids for role in member.roles
        )
    else:
        authorized = is_staff(member)
 
    if not authorized:
        await interaction.response.send_message(
            "❌ Tu n'as pas la permission de valider les absences.", ephemeral=True
        )
        return
 
    target_member = interaction.guild.get_member(target_user_id)
    try:
        target_user = target_member or await bot.fetch_user(target_user_id)
        await target_user.send("Bonjour,\n\nVotre absences a été validé.")
        dm_status = "✅ Message privé envoyé à l'utilisateur."
    except discord.Forbidden:
        dm_status = "⚠️ Impossible d'envoyer le message privé (DMs fermés)."
    except discord.HTTPException:
        dm_status = "⚠️ Erreur lors de l'envoi du message privé."
 
    embed = interaction.message.embeds[0]
    embed.color = discord.Color.green()
    if embed.fields and embed.fields[-1].name == "Statut":
        embed.set_field_at(len(embed.fields) - 1, name="Statut", value=f"✅ Validée par {interaction.user.mention}", inline=False)
    else:
        embed.add_field(name="Statut", value=f"✅ Validée par {interaction.user.mention}", inline=False)
 
    await interaction.message.edit(embed=embed, view=None)
    await interaction.response.send_message(f"Absence validée. {dm_status}", ephemeral=True)
 
 
@bot.command(name="absences")
async def absences_command(ctx: commands.Context):
    if not is_staff(ctx.author):
        await ctx.send("❌ Cette commande est réservée au staff.")
        return
 
    embed = discord.Embed(
        title="📋 Déclaration d'absence",
        description="Clique sur le bouton ci-dessous pour remplir le formulaire d'absence.",
        color=discord.Color.orange(),
    )
    await ctx.send(embed=embed, view=AbsenceView())
 
 
# ================================================================
#                    +role-react setup
# ================================================================
 
def parse_role_from_text(guild: discord.Guild, text: str) -> discord.Role | None:
    text = text.strip()
    if text.startswith("<@&") and text.endswith(">"):
        try:
            role_id = int(text[3:-1])
        except ValueError:
            return None
        return guild.get_role(role_id)
    return discord.utils.get(guild.roles, name=text)
 
 
@bot.command(name="role-react")
async def role_react_command(ctx: commands.Context, sous_commande: str = None):
    if sous_commande is None or sous_commande.lower() != "setup":
        await ctx.send("Utilise `+role-react setup` pour créer un message à réactions.")
        return
 
    if not is_staff(ctx.author):
        await ctx.send("❌ Cette commande est réservée au staff.")
        return
 
    def check(m: discord.Message) -> bool:
        return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id
 
    try:
        await ctx.send("📝 Envoie le **titre** du message (ou `annuler` pour arrêter).")
        msg_title = await bot.wait_for("message", check=check, timeout=120)
        if msg_title.content.lower() == "annuler":
            await ctx.send("❌ Configuration annulée.")
            return
        titre = msg_title.content
 
        await ctx.send("📝 Envoie maintenant la **description** du message.")
        msg_desc = await bot.wait_for("message", check=check, timeout=120)
        if msg_desc.content.lower() == "annuler":
            await ctx.send("❌ Configuration annulée.")
            return
        description = msg_desc.content
 
        await ctx.send(
            "📝 Envoie maintenant la liste **emoji + rôle**, une paire par ligne.\n"
            "Exemple :\n🔴 @Rouge\n🔵 @Bleu\n\n"
            "(emojis Discord classiques ou personnalisés du serveur, rôles en mention `@rôle`)"
        )
        msg_pairs = await bot.wait_for("message", check=check, timeout=180)
        if msg_pairs.content.lower() == "annuler":
            await ctx.send("❌ Configuration annulée.")
            return
 
        pairs = {}
        lines_summary = []
        for line in msg_pairs.content.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split(maxsplit=1)
            if len(parts) != 2:
                continue
            emoji_str, role_part = parts
            role = parse_role_from_text(ctx.guild, role_part)
            if role is None:
                continue
            pairs[emoji_str] = role.id
            lines_summary.append(f"{emoji_str} → {role.mention}")
 
        if not pairs:
            await ctx.send("❌ Aucune paire emoji/rôle valide détectée. Recommence avec `+role-react setup`.")
            return
 
        embed = discord.Embed(title=titre, description=description, color=discord.Color.blue())
        embed.add_field(name="Rôles disponibles", value="\n".join(lines_summary), inline=False)
        embed.set_footer(text="Réagis avec l'emoji correspondant pour obtenir le rôle.")
 
        role_message = await ctx.send(embed=embed)
 
        for emoji_str in pairs:
            try:
                await role_message.add_reaction(emoji_str)
            except discord.HTTPException:
                pass
 
        guild_conf = config.setdefault(str(ctx.guild.id), {})
        role_react_conf = guild_conf.setdefault("role_react", {})
        role_react_conf[str(role_message.id)] = pairs
        save_config(config)
 
        await ctx.send("✅ Le message à réactions a été créé avec succès !")
 
    except asyncio.TimeoutError:
        await ctx.send("⏱️ Temps écoulé, configuration annulée.")
 
 
@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.guild_id is None or payload.member is None or payload.member.bot:
        return
 
    mapping = config.get(str(payload.guild_id), {}).get("role_react", {}).get(str(payload.message_id))
    if not mapping:
        return
 
    role_id = mapping.get(str(payload.emoji))
    if role_id is None:
        return
 
    guild = bot.get_guild(payload.guild_id)
    role = guild.get_role(role_id) if guild else None
    if role:
        try:
            await payload.member.add_roles(role, reason="Role-react")
        except discord.HTTPException:
            pass
 
 
@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    if payload.guild_id is None:
        return
 
    mapping = config.get(str(payload.guild_id), {}).get("role_react", {}).get(str(payload.message_id))
    if not mapping:
        return
 
    role_id = mapping.get(str(payload.emoji))
    if role_id is None:
        return
 
    guild = bot.get_guild(payload.guild_id)
    if guild is None:
        return
    member = guild.get_member(payload.user_id)
    if member is None or member.bot:
        return
 
    role = guild.get_role(role_id)
    if role:
        try:
            await member.remove_roles(role, reason="Role-react retiré")
        except discord.HTTPException:
            pass
 
 
# ================================================================
#                    /ticketsetup — SYSTÈME DE TICKETS
# ================================================================
#
# +ticketsetup ouvre une fenêtre (modal) qui permet de tout personnaliser
# en une seule fois : titre de l'embed, texte au-dessus, texte en dessous,
# et la liste des boutons (label, emoji, couleur), exactement comme dans
# le screenshot fourni (plusieurs boutons de couleurs différentes qui
# ouvrent chacun un salon de ticket privé).
#
# Format d'une ligne de bouton dans le modal :
#   Label | emoji (optionnel) | couleur (optionnel)
# Couleurs acceptées : blurple/primary/bleu, green/vert/success,
#                      grey/gray/gris/secondary, red/rouge/danger
#
# Exemple :
#   Porter Plainte | 📩 | blurple
#   Contacter le Corps des Officiers | 📩 | green
#   Contacter les Brigades Spéciales | 📩 | grey
 
TICKET_STYLE_MAP = {
    "blurple": discord.ButtonStyle.primary,
    "primary": discord.ButtonStyle.primary,
    "bleu": discord.ButtonStyle.primary,
    "blue": discord.ButtonStyle.primary,
    "green": discord.ButtonStyle.success,
    "vert": discord.ButtonStyle.success,
    "success": discord.ButtonStyle.success,
    "grey": discord.ButtonStyle.secondary,
    "gray": discord.ButtonStyle.secondary,
    "gris": discord.ButtonStyle.secondary,
    "secondary": discord.ButtonStyle.secondary,
    "red": discord.ButtonStyle.danger,
    "rouge": discord.ButtonStyle.danger,
    "danger": discord.ButtonStyle.danger,
}
 
 
def get_ticket_panels(guild_id: int) -> dict:
    return config.get(str(guild_id), {}).get("ticket_panels", {})
 
 
def save_ticket_panel(guild_id: int, panel_id: str, buttons_data: list, category_name: str, ping_role_ids: list | None = None) -> None:
    guild_conf = config.setdefault(str(guild_id), {})
    ticket_panels = guild_conf.setdefault("ticket_panels", {})
    ticket_panels[panel_id] = {
        "buttons": buttons_data,
        "category_name": category_name,
        "ping_role_ids": ping_role_ids or [],
    }
    save_config(config)
 
 
class TicketButton(discord.ui.Button):
    """Bouton dynamique de panneau de tickets. Le custom_id encode panel_id et index
    pour retrouver la configuration du bouton, même après un redémarrage du bot."""
 
    async def callback(self, interaction: discord.Interaction):
        await handle_ticket_open(interaction, self.custom_id)
 
 
def build_ticket_panel_view(panel_id: str, buttons_data: list) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    for idx, data in enumerate(buttons_data):
        style = getattr(discord.ButtonStyle, data.get("style", "primary"), discord.ButtonStyle.primary)
        emoji = data.get("emoji") or None
        view.add_item(
            TicketButton(
                label=data["label"],
                emoji=emoji,
                style=style,
                custom_id=f"ticket_open:{panel_id}:{idx}",
            )
        )
    return view
 
 
async def handle_ticket_open(interaction: discord.Interaction, custom_id: str) -> None:
    try:
        _, panel_id, idx_str = custom_id.split(":", 2)
        idx = int(idx_str)
    except ValueError:
        return
 
    guild = interaction.guild
    if guild is None:
        return
 
    guild_conf = config.setdefault(str(guild.id), {})
    panel_conf = guild_conf.get("ticket_panels", {}).get(panel_id)
    if not panel_conf or idx >= len(panel_conf["buttons"]):
        await interaction.response.send_message("❌ Ce panneau de tickets n'est plus valide.", ephemeral=True)
        return
 
    bouton_conf = panel_conf["buttons"][idx]
    label = bouton_conf["label"]
 
    tickets_open = guild_conf.setdefault("tickets_open", {})
    open_key = f"{interaction.user.id}:{panel_id}:{idx}"
    existing_channel_id = tickets_open.get(open_key)
    if existing_channel_id:
        existing_channel = guild.get_channel(existing_channel_id)
        if existing_channel:
            await interaction.response.send_message(
                f"⚠️ Tu as déjà un ticket ouvert pour **{label}** : {existing_channel.mention}", ephemeral=True
            )
            return
        del tickets_open[open_key]
 
    await interaction.response.defer(ephemeral=True)
 
    category_name = panel_conf.get("category_name") or TICKETS_CATEGORY_NAME
    category = discord.utils.get(guild.categories, name=category_name)
    if category is None:
        try:
            category = await guild.create_category(category_name)
        except discord.Forbidden:
            await interaction.followup.send("❌ Je n'ai pas la permission de créer la catégorie de tickets.", ephemeral=True)
            return
 
    staff_role = discord.utils.get(guild.roles, name=STAFF_ROLE_NAME)
    ping_role_ids = panel_conf.get("ping_role_ids") or []
    ping_roles = [r for r in (guild.get_role(rid) for rid in ping_role_ids) if r is not None]

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, read_message_history=True),
    }
    if staff_role:
        overwrites[staff_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
    for role in ping_roles:
        overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
 
    slug = "".join(c if c.isalnum() else "-" for c in label.lower()).strip("-")[:40] or "ticket"
    channel_name = f"ticket-{slug}-{interaction.user.name}".lower()[:90]
 
    try:
        ticket_channel = await guild.create_text_channel(
            channel_name,
            category=category,
            overwrites=overwrites,
            topic=f"ticket_owner:{interaction.user.id}",
            reason=f"Ticket ouvert par {interaction.user} ({label})",
        )
    except discord.Forbidden:
        await interaction.followup.send("❌ Je n'ai pas la permission de créer un salon de ticket.", ephemeral=True)
        return
    except discord.HTTPException:
        await interaction.followup.send("❌ Erreur lors de la création du salon de ticket.", ephemeral=True)
        return
 
    tickets_open[open_key] = ticket_channel.id
    save_config(config)
 
    ticket_embed = discord.Embed(
        title=f"🎫 {label}",
        description=(
            f"Bonjour {interaction.user.mention}, merci d'avoir ouvert un ticket.\n\n"
            "Explique ta demande en détail ci-dessous, un membre du staff te répondra dès que possible."
        ),
        color=discord.Color.blurple(),
    )
    if ping_roles:
        mention_text = " ".join(role.mention for role in ping_roles)
    elif staff_role:
        mention_text = staff_role.mention
    else:
        mention_text = ""
    await ticket_channel.send(content=f"{interaction.user.mention} {mention_text}".strip(), embed=ticket_embed, view=TicketCloseView())
 
    await interaction.followup.send(f"✅ Ton ticket a été créé : {ticket_channel.mention}", ephemeral=True)
 
 
class TicketCloseView(discord.ui.View):
    """Vue statique (custom_id fixe) affichée dans chaque salon de ticket pour le fermer."""
 
    def __init__(self):
        super().__init__(timeout=None)
 
    @discord.ui.button(label="🔒 Fermer le ticket", style=discord.ButtonStyle.danger, custom_id="ticket_close")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = interaction.channel
        topic = channel.topic or ""
        owner_id = None
        if topic.startswith("ticket_owner:"):
            try:
                owner_id = int(topic.split(":", 1)[1])
            except ValueError:
                owner_id = None
 
        if not (is_staff(interaction.user) or interaction.user.id == owner_id):
            await interaction.response.send_message("❌ Tu ne peux pas fermer ce ticket.", ephemeral=True)
            return
 
        await interaction.response.send_message(f"🔒 Ticket fermé par {interaction.user.mention}. Suppression dans 5 secondes...")
 
        guild_conf = config.get(str(interaction.guild.id), {})
        tickets_open = guild_conf.get("tickets_open", {})
        key_to_remove = next((k for k, v in tickets_open.items() if v == channel.id), None)
        if key_to_remove:
            del tickets_open[key_to_remove]
            save_config(config)
 
        await asyncio.sleep(5)
        try:
            await channel.delete(reason=f"Ticket fermé par {interaction.user}")
        except discord.HTTPException:
            pass
 
 
class TicketSetupModal(discord.ui.Modal, title="Configuration du panneau de tickets"):
    titre = discord.ui.TextInput(
        label="Titre de l'embed",
        placeholder="Ex : 📩 Centre d'assistance",
        max_length=256,
    )
    texte_haut = discord.ui.TextInput(
        label="Texte au-dessus des boutons",
        style=discord.TextStyle.paragraph,
        placeholder="Explique le fonctionnement du système de tickets...",
        max_length=1000,
    )
    texte_bas = discord.ui.TextInput(
        label="Texte en dessous (optionnel)",
        style=discord.TextStyle.paragraph,
        placeholder="Infos complémentaires, règles, horaires de réponse...",
        required=False,
        max_length=1000,
    )
    boutons = discord.ui.TextInput(
        label="Boutons : Label | emoji | couleur",
        style=discord.TextStyle.paragraph,
        placeholder="Porter Plainte | 📩 | blurple\nAutre Contact | 📩 | green",
        max_length=1000,
    )
    categorie_nom = discord.ui.TextInput(
        label="Nom de la catégorie tickets (optionnel)",
        placeholder=f"Par défaut : {TICKETS_CATEGORY_NAME}",
        required=False,
        max_length=100,
    )
 
    async def on_submit(self, interaction: discord.Interaction):
        buttons_data = []
        for line in self.boutons.value.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split("|")]
            label = parts[0] if parts else ""
            if not label:
                continue
            emoji = parts[1] if len(parts) >= 2 and parts[1] else None
            style_key = parts[2].lower() if len(parts) >= 3 and parts[2] else "primary"
            style_enum = TICKET_STYLE_MAP.get(style_key, discord.ButtonStyle.primary)
            buttons_data.append({"label": label[:80], "emoji": emoji, "style": style_enum.name})
 
        if not buttons_data:
            await interaction.response.send_message(
                "❌ Aucun bouton valide détecté. Format attendu : `Label | emoji | couleur` (un par ligne).",
                ephemeral=True,
            )
            return
 
        if len(buttons_data) > 20:
            buttons_data = buttons_data[:20]
 
        category_name = self.categorie_nom.value.strip() or TICKETS_CATEGORY_NAME
        embed_data = {
            "titre": self.titre.value,
            "texte_haut": self.texte_haut.value,
            "texte_bas": self.texte_bas.value,
        }
 
        # Discord n'autorise pas les menus déroulants dans une fenêtre (modal) —
        # uniquement des champs texte. Dernière étape, juste après : un menu
        # déroulant natif listant tous les rôles du serveur (scrollable) pour
        # choisir qui sera ping à l'ouverture d'un ticket.
        await interaction.response.send_message(
            "🔧 Dernière étape : choisis le(s) rôle(s) à ping quand un ticket est ouvert, "
            "ou clique sur **Passer** pour ne ping personne.",
            view=TicketRoleSelectView(buttons_data, category_name, embed_data),
            ephemeral=True,
        )
 
 
class TicketRoleSelectView(discord.ui.View):
    """Étape finale de /ticketsetup : menu déroulant natif listant tous les rôles
    du serveur (scrollable), pour choisir qui est ping à l'ouverture d'un ticket."""

    def __init__(self, buttons_data: list, category_name: str, embed_data: dict):
        super().__init__(timeout=300)
        self.buttons_data = buttons_data
        self.category_name = category_name
        self.embed_data = embed_data
        self._done = False

    @discord.ui.select(
        cls=discord.ui.RoleSelect,
        placeholder="Rôle(s) à ping à l'ouverture d'un ticket (optionnel)",
        min_values=0,
        max_values=5,
    )
    async def role_select(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        role_ids = [role.id for role in select.values]
        await self._finalize(interaction, role_ids)

    @discord.ui.button(label="Passer (aucun ping)", style=discord.ButtonStyle.secondary)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._finalize(interaction, [])

    async def _finalize(self, interaction: discord.Interaction, role_ids: list):
        if self._done:
            return
        self._done = True

        panel_id = uuid.uuid4().hex
        save_ticket_panel(interaction.guild.id, panel_id, self.buttons_data, self.category_name, role_ids)

        embed = discord.Embed(
            title=self.embed_data["titre"],
            description=self.embed_data["texte_haut"],
            color=discord.Color.from_rgb(20, 20, 24),
        )
        if self.embed_data["texte_bas"]:
            embed.add_field(name="\u200b", value=self.embed_data["texte_bas"], inline=False)

        panel_view = build_ticket_panel_view(panel_id, self.buttons_data)

        self.stop()
        await interaction.response.edit_message(
            content="✅ Panneau de tickets configuré et envoyé ci-dessous !", view=None
        )
        await interaction.channel.send(embed=embed, view=panel_view)
 
 
@bot.tree.command(name="ticketsetup", description="[Staff] Crée un panneau de tickets personnalisable")
async def ticketsetup(interaction: discord.Interaction):
    if not is_staff(interaction.user):
        await interaction.response.send_message(
            "❌ Tu n'as pas la permission d'utiliser cette commande.", ephemeral=True
        )
        return
    await interaction.response.send_modal(TicketSetupModal())
 
 
# ================================================================
#          SYSTÈME D'ANNIVERSAIRES (optionnel, /anniv config)
# ================================================================
#
# Le système est désactivé par défaut sur un serveur : il faut que le staff
# fasse /anniv config pour choisir le salon d'annonce (et éventuellement
# personnaliser le message). Une fois configuré, les membres peuvent utiliser
# /anniversaire create pour enregistrer leur date (jour + mois uniquement,
# jamais l'année — donc pas de date de naissance ni de calcul d'âge).
# Chaque membre ne peut enregistrer qu'un seul anniversaire (utiliser
# /anniversaire modifier pour le changer).

ANNIV_CHECK_TIME = dt_time(hour=9, minute=0, tzinfo=PARIS_TZ)  # Heure de vérification quotidienne
ANNIV_DEFAULT_MESSAGE = "🎉🎂 Joyeux anniversaire {membre} !"


def is_anniv_enabled(guild_id: int) -> bool:
    return bool(config.get(str(guild_id), {}).get("anniv_config", {}).get("channel_id"))


def parse_anniv_date(date_str: str):
    """Parse une date au format JJ/MM (l'année, si fournie, est ignorée).
    Retourne (jour, mois) ou None si invalide."""
    parts = [p for p in re.split(r"[\/\-\. ]+", date_str.strip()) if p]
    if len(parts) < 2:
        return None
    try:
        jour = int(parts[0])
        mois = int(parts[1])
    except ValueError:
        return None

    if not (1 <= mois <= 12):
        return None
    # 2024 est bissextile : autorise le 29 février dans tous les cas.
    max_jour = calendar.monthrange(2024, mois)[1]
    if not (1 <= jour <= max_jour):
        return None

    return jour, mois


@tasks.loop(time=ANNIV_CHECK_TIME)
async def check_anniversaires():
    now = datetime.now(PARIS_TZ)
    for guild in bot.guilds:
        guild_conf = config.get(str(guild.id), {})
        anniv_conf = guild_conf.get("anniv_config")
        if not anniv_conf or not anniv_conf.get("channel_id"):
            continue

        channel = guild.get_channel(anniv_conf["channel_id"])
        if channel is None:
            continue

        message_template = anniv_conf.get("message") or ANNIV_DEFAULT_MESSAGE
        birthdays = guild_conf.get("birthdays", {})

        for user_id, bday in birthdays.items():
            if bday.get("day") == now.day and bday.get("month") == now.month:
                member = guild.get_member(int(user_id))
                if member is None:
                    continue
                texte = message_template.replace("{membre}", member.mention)
                try:
                    await channel.send(texte)
                except discord.HTTPException:
                    pass


@check_anniversaires.before_loop
async def before_check_anniversaires():
    await bot.wait_until_ready()


anniv_group = app_commands.Group(name="anniv", description="Configuration du système d'anniversaires (staff)")


@anniv_group.command(name="config", description="[Staff] Active/configure le système d'anniversaires")
@app_commands.describe(
    salon="Salon où seront annoncés les anniversaires",
    message="Message personnalisé (utilise {membre} pour mentionner la personne)",
)
async def anniv_config_cmd(interaction: discord.Interaction, salon: discord.TextChannel, message: str = None):
    if not is_staff(interaction.user):
        await interaction.response.send_message(
            "❌ Tu n'as pas la permission d'utiliser cette commande.", ephemeral=True
        )
        return

    guild_conf = config.setdefault(str(interaction.guild.id), {})
    anniv_conf = guild_conf.setdefault("anniv_config", {})
    anniv_conf["channel_id"] = salon.id
    if message:
        anniv_conf["message"] = message
    save_config(config)

    await interaction.response.send_message(
        f"✅ Système d'anniversaires activé ! Les anniversaires seront annoncés dans {salon.mention} "
        "chaque jour à 9h (heure de Paris).\n"
        "Les membres peuvent maintenant utiliser `/anniversaire create`.",
        ephemeral=True,
    )


@anniv_group.command(name="desactiver", description="[Staff] Désactive le système d'anniversaires")
async def anniv_desactiver_cmd(interaction: discord.Interaction):
    if not is_staff(interaction.user):
        await interaction.response.send_message(
            "❌ Tu n'as pas la permission d'utiliser cette commande.", ephemeral=True
        )
        return

    guild_conf = config.setdefault(str(interaction.guild.id), {})
    if "anniv_config" in guild_conf:
        del guild_conf["anniv_config"]
        save_config(config)

    await interaction.response.send_message("✅ Système d'anniversaires désactivé sur ce serveur.", ephemeral=True)


bot.tree.add_command(anniv_group)


anniversaire_group = app_commands.Group(name="anniversaire", description="Gère ton anniversaire (jour/mois uniquement)")


@anniversaire_group.command(name="create", description="Enregistre ton anniversaire (jour/mois uniquement)")
@app_commands.describe(date="Date de ton anniversaire au format JJ/MM (ex : 25/12). Aucune année demandée.")
async def anniversaire_create_cmd(interaction: discord.Interaction, date: str):
    if not is_anniv_enabled(interaction.guild.id):
        await interaction.response.send_message(
            "❌ Le système d'anniversaires n'est pas activé sur ce serveur.", ephemeral=True
        )
        return

    parsed = parse_anniv_date(date)
    if parsed is None:
        await interaction.response.send_message(
            "❌ Format de date invalide. Utilise `JJ/MM`, par exemple `25/12`.", ephemeral=True
        )
        return
    jour, mois = parsed

    guild_conf = config.setdefault(str(interaction.guild.id), {})
    birthdays = guild_conf.setdefault("birthdays", {})
    uid = str(interaction.user.id)

    if uid in birthdays:
        await interaction.response.send_message(
            "⚠️ Tu as déjà enregistré un anniversaire. Utilise `/anniversaire modifier` pour le changer.",
            ephemeral=True,
        )
        return

    birthdays[uid] = {"day": jour, "month": mois}
    save_config(config)

    await interaction.response.send_message(
        f"✅ Ton anniversaire ({jour:02d}/{mois:02d}) a bien été enregistré 🎉 (aucune année n'est demandée ni stockée).",
        ephemeral=True,
    )


@anniversaire_group.command(name="modifier", description="Modifie la date de ton anniversaire déjà enregistré")
@app_commands.describe(date="Nouvelle date au format JJ/MM (ex : 25/12)")
async def anniversaire_modifier_cmd(interaction: discord.Interaction, date: str):
    if not is_anniv_enabled(interaction.guild.id):
        await interaction.response.send_message(
            "❌ Le système d'anniversaires n'est pas activé sur ce serveur.", ephemeral=True
        )
        return

    parsed = parse_anniv_date(date)
    if parsed is None:
        await interaction.response.send_message(
            "❌ Format de date invalide. Utilise `JJ/MM`, par exemple `25/12`.", ephemeral=True
        )
        return
    jour, mois = parsed

    guild_conf = config.setdefault(str(interaction.guild.id), {})
    birthdays = guild_conf.setdefault("birthdays", {})
    uid = str(interaction.user.id)

    if uid not in birthdays:
        await interaction.response.send_message(
            "❌ Tu n'as pas encore d'anniversaire enregistré. Utilise `/anniversaire create`.", ephemeral=True
        )
        return

    birthdays[uid] = {"day": jour, "month": mois}
    save_config(config)

    await interaction.response.send_message(f"✅ Ton anniversaire a été mis à jour : {jour:02d}/{mois:02d}.", ephemeral=True)


@anniversaire_group.command(name="supprimer", description="Supprime ton anniversaire enregistré")
async def anniversaire_supprimer_cmd(interaction: discord.Interaction):
    guild_conf = config.setdefault(str(interaction.guild.id), {})
    birthdays = guild_conf.setdefault("birthdays", {})
    uid = str(interaction.user.id)

    if uid not in birthdays:
        await interaction.response.send_message("❌ Tu n'as pas d'anniversaire enregistré.", ephemeral=True)
        return

    del birthdays[uid]
    save_config(config)
    await interaction.response.send_message("✅ Ton anniversaire a été supprimé.", ephemeral=True)


@anniversaire_group.command(name="liste", description="Affiche les prochains anniversaires du serveur")
async def anniversaire_liste_cmd(interaction: discord.Interaction):
    guild_conf = config.get(str(interaction.guild.id), {})
    birthdays = guild_conf.get("birthdays", {})

    if not birthdays:
        await interaction.response.send_message("Aucun anniversaire enregistré pour le moment.", ephemeral=True)
        return

    today = datetime.now(PARIS_TZ).date()

    def prochaine_occurrence(jour: int, mois: int):
        annee = today.year
        try:
            d = datetime(annee, mois, jour, tzinfo=PARIS_TZ).date()
        except ValueError:
            d = datetime(annee, 3, 1, tzinfo=PARIS_TZ).date()
        if d < today:
            try:
                d = datetime(annee + 1, mois, jour, tzinfo=PARIS_TZ).date()
            except ValueError:
                d = datetime(annee + 1, 3, 1, tzinfo=PARIS_TZ).date()
        return d

    entries = []
    for uid, bday in birthdays.items():
        prochaine = prochaine_occurrence(bday["day"], bday["month"])
        entries.append((prochaine, uid, bday))
    entries.sort(key=lambda e: e[0])

    lignes = []
    for prochaine, uid, bday in entries[:15]:
        member = interaction.guild.get_member(int(uid))
        nom = member.mention if member else f"<@{uid}>"
        date_str = f"{bday['day']:02d}/{bday['month']:02d}"
        delta = (prochaine - today).days
        suffix = "🎉 **Aujourd'hui !**" if delta == 0 else f"dans {delta} jour(s)"
        lignes.append(f"• {nom} — {date_str} ({suffix})")

    embed = discord.Embed(
        title="🎂 Prochains anniversaires",
        description="\n".join(lignes),
        color=discord.Color.pink(),
    )
    await interaction.response.send_message(embed=embed)


bot.tree.add_command(anniversaire_group)
 
 
# ================================================================
#          NOTIFICATIONS TIKTOK (/config tiktok)
# ================================================================
#
# ⚠️ TikTok ne propose pas d'API publique officielle permettant de surveiller
# les nouvelles vidéos d'un compte arbitraire. La méthode ci-dessous analyse
# le HTML public de la page de profil (aucune connexion ni identifiant TikTok
# requis) pour retrouver la dernière vidéo publiée. TikTok modifie
# régulièrement la structure de ses pages et peut bloquer les requêtes
# automatisées : cette fonctionnalité est donc fournie en best-effort et peut
# nécessiter une maintenance si TikTok change son site.

async def fetch_latest_tiktok_video(username: str):
    """Récupère {id, url, description} de la dernière vidéo publique du compte,
    ou None si indisponible/erreur."""
    url = f"https://www.tiktok.com/@{username}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    }

    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text()
    except (aiohttp.ClientError, asyncio.TimeoutError):
        return None

    match = re.search(
        r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>',
        html,
        re.DOTALL,
    )
    if not match:
        return None

    try:
        data = json.loads(match.group(1))
        item_list = data["__DEFAULT_SCOPE__"]["webapp.user-detail"]["userInfo"]["itemList"]
    except (KeyError, TypeError, json.JSONDecodeError):
        return None

    if not item_list:
        return None

    latest = max(item_list, key=lambda it: int(it.get("createTime", 0) or 0))
    video_id = latest.get("id")
    if not video_id:
        return None

    return {
        "id": str(video_id),
        "url": f"https://www.tiktok.com/@{username}/video/{video_id}",
        "description": latest.get("desc", ""),
    }


@tasks.loop(minutes=TIKTOK_CHECK_INTERVAL_MINUTES)
async def check_tiktok_loop():
    video = await fetch_latest_tiktok_video(TIKTOK_USERNAME)
    if not video:
        return

    last_id = config.get("tiktok_last_video_id")
    if last_id is None:
        # Premier lancement : on mémorise la vidéo actuelle sans notifier,
        # pour ne pas spammer avec d'anciennes vidéos.
        config["tiktok_last_video_id"] = video["id"]
        save_config(config)
        return

    if video["id"] == last_id:
        return

    config["tiktok_last_video_id"] = video["id"]
    save_config(config)

    for guild in bot.guilds:
        guild_conf = config.get(str(guild.id), {})
        tiktok_conf = guild_conf.get("tiktok_config")
        if not tiktok_conf or not tiktok_conf.get("channel_id") or not tiktok_conf.get("actif", True):
            continue

        channel = guild.get_channel(tiktok_conf["channel_id"])
        if channel is None:
            continue

        template = tiktok_conf.get("message") or (
            f"📱 Nouvelle vidéo TikTok de **@{TIKTOK_USERNAME}** !\n{{lien}}"
        )
        texte = template.replace("{lien}", video["url"]).replace("{compte}", f"@{TIKTOK_USERNAME}")
        try:
            await channel.send(texte)
        except discord.HTTPException:
            pass


@check_tiktok_loop.before_loop
async def before_check_tiktok_loop():
    await bot.wait_until_ready()


config_group = app_commands.Group(name="config", description="Commandes de configuration du bot")


@config_group.command(name="tiktok", description=f"[Staff] Configure les notifications de nouvelles vidéos de @{TIKTOK_USERNAME}")
@app_commands.describe(
    salon="Salon où seront envoyées les notifications de nouvelles vidéos",
    message="Message personnalisé (utilise {lien} pour le lien de la vidéo et {compte} pour le nom du compte)",
    actif="Active ou désactive les notifications (activé par défaut)",
)
async def config_tiktok_cmd(
    interaction: discord.Interaction,
    salon: discord.TextChannel,
    message: str = None,
    actif: bool = True,
):
    if not is_staff(interaction.user):
        await interaction.response.send_message(
            "❌ Tu n'as pas la permission d'utiliser cette commande.", ephemeral=True
        )
        return

    guild_conf = config.setdefault(str(interaction.guild.id), {})
    tiktok_conf = guild_conf.setdefault("tiktok_config", {})
    tiktok_conf["channel_id"] = salon.id
    tiktok_conf["actif"] = actif
    if message:
        tiktok_conf["message"] = message
    save_config(config)

    etat = "activées ✅" if actif else "désactivées ⏸️"
    await interaction.response.send_message(
        f"✅ Notifications TikTok pour **@{TIKTOK_USERNAME}** configurées sur {salon.mention} ({etat}).",
        ephemeral=True,
    )


bot.tree.add_command(config_group)
 
 
# ================================================================
#      SYSTÈME D'ANIMAUX À CAPTURER (optionnel, /animal config)
# ================================================================
#
# Chaque jour, à une heure aléatoire, un animal sauvage apparaît dans le
# salon configuré. Le premier membre à cliquer sur "Capturer !" le remporte.
# La rareté de l'animal qui apparaît est tirée au sort selon les pourcentages
# ci-dessous, puis un animal est choisi au hasard parmi ceux de cette rareté.

ANIMAUX = [
    {"nom": "Yuzenn", "rarete": "Owner"},
    {"nom": "Snow", "rarete": "Owner"},
    {"nom": "Rebeu", "rarete": "Co-Owner"},
    {"nom": "Cafard", "rarete": "Modérateur"},
    {"nom": "R0tten", "rarete": "VIP"},
    {"nom": "Lgz", "rarete": "VIP"},
    {"nom": "9z_wl", "rarete": "Membre"},
    {"nom": "Beurre2KKhouette", "rarete": "Membre"},
    {"nom": "Slayzxx", "rarete": "Membre"},
    {"nom": "doren99", "rarete": "Membre"},
    {"nom": "Ryzz", "rarete": "Modérateur"},
    {"nom": "Velvelte", "rarete": "Animateur"},
]

RARETE_WEIGHTS = {
    "Owner": 0.5,
    "Co-Owner": 2,
    "Modérateur": 10,
    "Animateur": 8,
    "VIP": 20,
    "Membre": 59.5,
}

RARETE_COLORS = {
    "Owner": discord.Color.red(),
    "Co-Owner": discord.Color.orange(),
    "Modérateur": discord.Color.purple(),
    "Animateur": discord.Color.green(),
    "VIP": discord.Color.gold(),
    "Membre": discord.Color.light_grey(),
}

ANIMAL_SPAWN_HOUR_MIN = 8       # Heure la plus tôt possible pour un spawn (heure de Paris)
ANIMAL_SPAWN_HOUR_MAX = 23      # Heure la plus tardive possible pour un spawn
ANIMAL_DESPAWN_SECONDS = 300    # Temps disponible pour capturer l'animal (5 minutes) avant qu'il ne s'enfuie
ANIMAL_CHECK_INTERVAL_MINUTES = 1

# Boost de chance temporaire (déclenché depuis /admin panel). En mémoire
# uniquement : {guild_id: {"multiplier": float, "expires_at": datetime}}
LUCK_BOOST: dict[int, dict] = {}


def get_active_luck_multiplier(guild_id: int) -> float:
    boost = LUCK_BOOST.get(guild_id)
    if not boost:
        return 1.0
    if datetime.now(PARIS_TZ) >= boost["expires_at"]:
        del LUCK_BOOST[guild_id]
        return 1.0
    return boost["multiplier"]


def pick_random_animal(guild_id: int | None = None) -> dict:
    """Tire une rareté selon les pourcentages configurés, puis un animal
    au hasard parmi ceux de cette rareté. Si un boost de chance est actif sur
    le serveur, les raretés autres que 'Membre' voient leur poids multiplié."""
    raretes = list(RARETE_WEIGHTS.keys())
    poids = list(RARETE_WEIGHTS.values())

    if guild_id is not None:
        multiplicateur = get_active_luck_multiplier(guild_id)
        if multiplicateur != 1.0:
            poids = [
                p if rarete == "Membre" else p * multiplicateur
                for rarete, p in zip(raretes, poids)
            ]

    rarete_choisie = random.choices(raretes, weights=poids, k=1)[0]
    candidats = [a for a in ANIMAUX if a["rarete"] == rarete_choisie]
    return random.choice(candidats)


def compute_next_spawn_datetime(base: datetime) -> datetime:
    """Calcule une heure aléatoire du jour suivant `base`, entre
    ANIMAL_SPAWN_HOUR_MIN et ANIMAL_SPAWN_HOUR_MAX (heure de Paris)."""
    heure = random.randint(ANIMAL_SPAWN_HOUR_MIN, ANIMAL_SPAWN_HOUR_MAX)
    minute = random.randint(0, 59)
    prochain_jour = base + timedelta(days=1)
    return prochain_jour.replace(hour=heure, minute=minute, second=0, microsecond=0)


def build_animal_spawn_embed(animal: dict) -> discord.Embed:
    color = RARETE_COLORS.get(animal["rarete"], discord.Color.blurple())
    embed = discord.Embed(
        title="🐾 Un animal sauvage est apparu !",
        description=f"Un **{animal['nom']}** rôde dans les parages...\nSois le premier à cliquer pour le capturer !",
        color=color,
    )
    embed.add_field(name="🐾 Espèce", value=animal["rarete"], inline=True)
    embed.add_field(name="⭐ Rareté", value=animal["rarete"], inline=True)
    embed.set_footer(text="Ce compagnon sauvage attend un maître...")
    return embed


def build_animal_captured_embed(animal: dict, user: discord.abc.User) -> discord.Embed:
    color = RARETE_COLORS.get(animal["rarete"], discord.Color.green())
    embed = discord.Embed(
        title=f"{animal['nom']} — Capturé !",
        description=f"{user.mention} a capturé **{animal['nom']}** !",
        color=color,
    )
    embed.add_field(name="🐾 Espèce", value=animal["rarete"], inline=True)
    embed.add_field(name="⭐ Rareté", value=animal["rarete"], inline=True)
    date_str = datetime.now(PARIS_TZ).strftime("%d/%m/%Y %H:%M")
    embed.set_footer(text=f"Ce compagnon a trouvé un maître. • {date_str}")
    return embed


def build_animal_escaped_embed(animal: dict) -> discord.Embed:
    embed = discord.Embed(
        title=f"{animal['nom']} — Enfui !",
        description=f"Personne n'a capturé **{animal['nom']}** à temps... il s'est enfui. 😢",
        color=discord.Color.dark_grey(),
    )
    embed.add_field(name="🐾 Espèce", value=animal["rarete"], inline=True)
    embed.add_field(name="⭐ Rareté", value=animal["rarete"], inline=True)
    return embed


class AnimalCaptureView(discord.ui.View):
    """Vue temporaire (non persistante) affichée sous un animal sauvage.
    Le premier clic sur le bouton remporte l'animal."""

    def __init__(self, animal: dict, guild_id: int):
        super().__init__(timeout=ANIMAL_DESPAWN_SECONDS)
        self.animal = animal
        self.guild_id = guild_id
        self.captured = False
        self.message: discord.Message | None = None

    @discord.ui.button(label="🎯 Capturer !", style=discord.ButtonStyle.primary)
    async def capturer(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.captured:
            await interaction.response.send_message(
                "😢 Trop tard, quelqu'un d'autre l'a déjà capturé !", ephemeral=True
            )
            return

        # Verrouillage immédiat (avant tout await) pour éviter qu'un double-clic
        # simultané ne fasse gagner l'animal à deux personnes à la fois.
        self.captured = True

        guild_conf = config.setdefault(str(self.guild_id), {})
        collections = guild_conf.setdefault("animal_collections", {})
        user_animaux = collections.setdefault(str(interaction.user.id), [])
        user_animaux.append(self.animal["nom"])
        save_config(config)

        embed = build_animal_captured_embed(self.animal, interaction.user)
        button.style = discord.ButtonStyle.success
        button.label = "✅ Capturé !"
        button.disabled = True
        self.stop()
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self):
        if self.captured or self.message is None:
            return
        embed = build_animal_escaped_embed(self.animal)
        for child in self.children:
            child.disabled = True
        try:
            await self.message.edit(embed=embed, view=self)
        except discord.HTTPException:
            pass


async def spawn_animal(guild: discord.Guild, channel: discord.abc.Messageable) -> None:
    animal = pick_random_animal(guild.id)
    embed = build_animal_spawn_embed(animal)
    view = AnimalCaptureView(animal, guild.id)
    message = await channel.send(embed=embed, view=view)
    view.message = message


@tasks.loop(minutes=ANIMAL_CHECK_INTERVAL_MINUTES)
async def check_animal_spawns():
    now = datetime.now(PARIS_TZ)
    for guild in bot.guilds:
        guild_conf = config.get(str(guild.id), {})
        animal_conf = guild_conf.get("animal_config")
        if not animal_conf or not animal_conf.get("channel_id"):
            continue

        next_spawn_iso = animal_conf.get("next_spawn")
        if not next_spawn_iso:
            # Pas encore de spawn programmé : on en programme un premier
            # (dès aujourd'hui, à une heure aléatoire restante).
            next_dt = compute_next_spawn_datetime(now - timedelta(days=1))
            animal_conf["next_spawn"] = next_dt.isoformat()
            save_config(config)
            continue

        next_dt = datetime.fromisoformat(next_spawn_iso)
        if next_dt.tzinfo is None:
            next_dt = next_dt.replace(tzinfo=PARIS_TZ)

        if now >= next_dt:
            channel = guild.get_channel(animal_conf["channel_id"])
            if channel:
                try:
                    await spawn_animal(guild, channel)
                except discord.HTTPException:
                    pass
            animal_conf["next_spawn"] = compute_next_spawn_datetime(now).isoformat()
            save_config(config)


@check_animal_spawns.before_loop
async def before_check_animal_spawns():
    await bot.wait_until_ready()


animal_group = app_commands.Group(name="animal", description="Système d'animaux à capturer")


@animal_group.command(name="config", description="[Staff] Active/configure le système d'animaux à capturer")
@app_commands.describe(salon="Salon où les animaux sauvages apparaîtront")
async def animal_config_cmd(interaction: discord.Interaction, salon: discord.TextChannel):
    if not is_staff(interaction.user):
        await interaction.response.send_message(
            "❌ Tu n'as pas la permission d'utiliser cette commande.", ephemeral=True
        )
        return

    guild_conf = config.setdefault(str(interaction.guild.id), {})
    animal_conf = guild_conf.setdefault("animal_config", {})
    animal_conf["channel_id"] = salon.id
    if "next_spawn" not in animal_conf:
        premiere_prog = compute_next_spawn_datetime(datetime.now(PARIS_TZ) - timedelta(days=1))
        animal_conf["next_spawn"] = premiere_prog.isoformat()
    save_config(config)

    await interaction.response.send_message(
        f"✅ Système d'animaux activé ! Un animal apparaîtra chaque jour à une heure aléatoire "
        f"(entre {ANIMAL_SPAWN_HOUR_MIN}h et {ANIMAL_SPAWN_HOUR_MAX}h) dans {salon.mention}.",
        ephemeral=True,
    )


@animal_group.command(name="desactiver", description="[Staff] Désactive le système d'animaux")
async def animal_desactiver_cmd(interaction: discord.Interaction):
    if not is_staff(interaction.user):
        await interaction.response.send_message(
            "❌ Tu n'as pas la permission d'utiliser cette commande.", ephemeral=True
        )
        return

    guild_conf = config.setdefault(str(interaction.guild.id), {})
    if "animal_config" in guild_conf:
        del guild_conf["animal_config"]
        save_config(config)

    await interaction.response.send_message("✅ Système d'animaux désactivé sur ce serveur.", ephemeral=True)


@animal_group.command(name="forcespawn", description="[Staff] Force l'apparition immédiate d'un animal")
async def animal_forcespawn_cmd(interaction: discord.Interaction):
    if not is_staff(interaction.user):
        await interaction.response.send_message(
            "❌ Tu n'as pas la permission d'utiliser cette commande.", ephemeral=True
        )
        return

    guild_conf = config.get(str(interaction.guild.id), {})
    animal_conf = guild_conf.get("animal_config")
    if not animal_conf or not animal_conf.get("channel_id"):
        await interaction.response.send_message(
            "❌ Le système d'animaux n'est pas configuré. Utilise `/animal config` d'abord.", ephemeral=True
        )
        return

    channel = interaction.guild.get_channel(animal_conf["channel_id"])
    if channel is None:
        await interaction.response.send_message("❌ Le salon configuré est introuvable.", ephemeral=True)
        return

    await interaction.response.send_message(f"✅ Un animal va apparaître dans {channel.mention} !", ephemeral=True)
    await spawn_animal(interaction.guild, channel)


@animal_group.command(name="collection", description="Affiche les animaux que tu as capturés")
async def animal_collection_cmd(interaction: discord.Interaction):
    guild_conf = config.get(str(interaction.guild.id), {})
    collections = guild_conf.get("animal_collections", {})
    mes_animaux = collections.get(str(interaction.user.id), [])

    if not mes_animaux:
        await interaction.response.send_message("Tu n'as encore capturé aucun animal.", ephemeral=True)
        return

    compteur: dict[str, int] = {}
    for nom in mes_animaux:
        compteur[nom] = compteur.get(nom, 0) + 1

    lignes = []
    for nom, count in sorted(compteur.items(), key=lambda x: -x[1]):
        rarete = next((a["rarete"] for a in ANIMAUX if a["nom"] == nom), "?")
        lignes.append(f"**{nom}** ({rarete}) x{count}")

    embed = discord.Embed(
        title=f"🐾 Collection de {interaction.user.display_name}",
        description="\n".join(lignes),
        color=discord.Color.blurple(),
    )
    embed.set_footer(text=f"{len(mes_animaux)} capture(s) au total")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@animal_group.command(name="classement", description="Affiche le classement des meilleurs chasseurs d'animaux")
async def animal_classement_cmd(interaction: discord.Interaction):
    guild_conf = config.get(str(interaction.guild.id), {})
    collections = guild_conf.get("animal_collections", {})

    if not collections:
        await interaction.response.send_message("Personne n'a encore capturé d'animal sur ce serveur.", ephemeral=True)
        return

    classement = sorted(collections.items(), key=lambda x: -len(x[1]))[:10]
    lignes = []
    for i, (uid, animaux) in enumerate(classement, start=1):
        member = interaction.guild.get_member(int(uid))
        nom = member.mention if member else f"<@{uid}>"
        lignes.append(f"**#{i}** — {nom} : {len(animaux)} capture(s)")

    embed = discord.Embed(
        title="🏆 Classement des chasseurs d'animaux",
        description="\n".join(lignes),
        color=discord.Color.gold(),
    )
    await interaction.response.send_message(embed=embed)


bot.tree.add_command(animal_group)
 
 
# ================================================================
#      INVENTAIRE ET ÉCHANGES D'ANIMAUX (/pet inventory, /pet trade)
# ================================================================
#
# /pet trade propose un échange 1 contre 1 : l'initiateur choisit un de ses
# animaux à donner et un animal que la cible possède déjà à recevoir. La
# cible doit ensuite cliquer sur "Accepter" pour que l'échange soit effectué.

def get_animal_counts(guild_id: int, user_id: int) -> dict:
    """Retourne {nom_animal: quantité} pour un membre donné."""
    guild_conf = config.get(str(guild_id), {})
    animaux_liste = guild_conf.get("animal_collections", {}).get(str(user_id), [])
    compteur: dict[str, int] = {}
    for nom in animaux_liste:
        compteur[nom] = compteur.get(nom, 0) + 1
    return compteur


def get_animal_rarete(nom: str) -> str:
    return next((a["rarete"] for a in ANIMAUX if a["nom"] == nom), "?")


class PetTradeConfirmView(discord.ui.View):
    """Vue affichée dans le salon, visible par la cible de l'échange, qui doit
    accepter ou refuser."""

    def __init__(self, initiateur: discord.Member, cible: discord.Member, animal_initiateur: str, animal_cible: str):
        super().__init__(timeout=300)
        self.initiateur = initiateur
        self.cible = cible
        self.animal_initiateur = animal_initiateur
        self.animal_cible = animal_cible
        self.resolved = False
        self.message: discord.Message | None = None

    @discord.ui.button(label="✅ Accepter", style=discord.ButtonStyle.success)
    async def accepter(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.cible.id:
            await interaction.response.send_message(
                "❌ Seul(e) la personne visée par cet échange peut y répondre.", ephemeral=True
            )
            return
        if self.resolved:
            return
        self.resolved = True

        guild_conf = config.setdefault(str(interaction.guild.id), {})
        collections = guild_conf.setdefault("animal_collections", {})
        animaux_initiateur = collections.setdefault(str(self.initiateur.id), [])
        animaux_cible = collections.setdefault(str(self.cible.id), [])

        if self.animal_initiateur not in animaux_initiateur or self.animal_cible not in animaux_cible:
            self.stop()
            for child in self.children:
                child.disabled = True
            await interaction.response.edit_message(
                content="❌ L'un des deux animaux n'est plus disponible (déjà échangé ?). Échange annulé.",
                embed=None,
                view=self,
            )
            return

        animaux_initiateur.remove(self.animal_initiateur)
        animaux_initiateur.append(self.animal_cible)
        animaux_cible.remove(self.animal_cible)
        animaux_cible.append(self.animal_initiateur)
        save_config(config)

        self.stop()
        for child in self.children:
            child.disabled = True

        embed = discord.Embed(
            title="✅ Échange effectué !",
            description=(
                f"{self.initiateur.mention} a donné **{self.animal_initiateur}** et reçu **{self.animal_cible}**.\n"
                f"{self.cible.mention} a donné **{self.animal_cible}** et reçu **{self.animal_initiateur}**."
            ),
            color=discord.Color.green(),
        )
        await interaction.response.edit_message(content=None, embed=embed, view=self)

    @discord.ui.button(label="❌ Refuser", style=discord.ButtonStyle.danger)
    async def refuser(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.cible.id:
            await interaction.response.send_message(
                "❌ Seul(e) la personne visée par cet échange peut y répondre.", ephemeral=True
            )
            return
        if self.resolved:
            return
        self.resolved = True
        self.stop()
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            content=f"❌ {self.cible.mention} a refusé l'échange.", embed=None, view=self
        )

    async def on_timeout(self):
        if self.resolved or self.message is None:
            return
        for child in self.children:
            child.disabled = True
        try:
            await self.message.edit(content="⏱️ Cet échange a expiré (personne n'a répondu à temps).", embed=None, view=self)
        except discord.HTTPException:
            pass


class PetTradeSetupView(discord.ui.View):
    """Vue éphémère (visible seulement par l'initiateur) pour choisir les deux
    animaux concernés avant d'envoyer la proposition."""

    def __init__(self, initiateur: discord.Member, cible: discord.Member, mes_animaux: list, leurs_animaux: list):
        super().__init__(timeout=120)
        self.initiateur = initiateur
        self.cible = cible
        self.mon_choix: str | None = None
        self.leur_choix: str | None = None

        self.select_mon_animal = discord.ui.Select(
            placeholder="Ton animal à proposer",
            options=self._build_options(mes_animaux),
            min_values=1,
            max_values=1,
        )
        self.select_mon_animal.callback = self.on_select_mon_animal
        self.add_item(self.select_mon_animal)

        self.select_leur_animal = discord.ui.Select(
            placeholder=f"Animal de {cible.display_name} à recevoir",
            options=self._build_options(leurs_animaux),
            min_values=1,
            max_values=1,
        )
        self.select_leur_animal.callback = self.on_select_leur_animal
        self.add_item(self.select_leur_animal)

        self.bouton_proposer = discord.ui.Button(
            label="Proposer l'échange", style=discord.ButtonStyle.primary, disabled=True
        )
        self.bouton_proposer.callback = self.on_proposer
        self.add_item(self.bouton_proposer)

    @staticmethod
    def _build_options(animaux_liste: list) -> list:
        uniques = sorted(set(animaux_liste))
        options = []
        for nom in uniques[:25]:
            rarete = get_animal_rarete(nom)
            count = animaux_liste.count(nom)
            options.append(discord.SelectOption(label=nom, description=f"{rarete} • x{count}", value=nom))
        return options

    def _maj_bouton(self):
        self.bouton_proposer.disabled = not (self.mon_choix and self.leur_choix)

    async def on_select_mon_animal(self, interaction: discord.Interaction):
        if interaction.user.id != self.initiateur.id:
            await interaction.response.send_message("❌ Ce n'est pas ton échange.", ephemeral=True)
            return
        self.mon_choix = self.select_mon_animal.values[0]
        self._maj_bouton()
        await interaction.response.edit_message(view=self)

    async def on_select_leur_animal(self, interaction: discord.Interaction):
        if interaction.user.id != self.initiateur.id:
            await interaction.response.send_message("❌ Ce n'est pas ton échange.", ephemeral=True)
            return
        self.leur_choix = self.select_leur_animal.values[0]
        self._maj_bouton()
        await interaction.response.edit_message(view=self)

    async def on_proposer(self, interaction: discord.Interaction):
        if interaction.user.id != self.initiateur.id:
            await interaction.response.send_message("❌ Ce n'est pas ton échange.", ephemeral=True)
            return

        guild_conf = config.get(str(interaction.guild.id), {})
        collections = guild_conf.get("animal_collections", {})
        mes_animaux_actuels = collections.get(str(self.initiateur.id), [])
        leurs_animaux_actuels = collections.get(str(self.cible.id), [])

        if self.mon_choix not in mes_animaux_actuels:
            self.stop()
            await interaction.response.edit_message(
                content=f"❌ Tu ne possèdes plus **{self.mon_choix}**. Échange annulé.", view=None
            )
            return
        if self.leur_choix not in leurs_animaux_actuels:
            self.stop()
            await interaction.response.edit_message(
                content=f"❌ {self.cible.mention} ne possède plus **{self.leur_choix}**. Échange annulé.", view=None
            )
            return

        self.stop()
        await interaction.response.edit_message(content=f"✅ Proposition envoyée à {self.cible.mention} !", view=None)

        rarete_mon = get_animal_rarete(self.mon_choix)
        rarete_leur = get_animal_rarete(self.leur_choix)
        embed = discord.Embed(
            title="🔄 Proposition d'échange",
            description=(
                f"{self.initiateur.mention} propose un échange à {self.cible.mention} :\n\n"
                f"**{self.initiateur.display_name}** donne : **{self.mon_choix}** ({rarete_mon})\n"
                f"**{self.cible.display_name}** donne : **{self.leur_choix}** ({rarete_leur})"
            ),
            color=discord.Color.blurple(),
        )
        embed.set_footer(text=f"{self.cible.display_name}, clique ci-dessous pour répondre (5 min).")

        confirm_view = PetTradeConfirmView(self.initiateur, self.cible, self.mon_choix, self.leur_choix)
        message = await interaction.channel.send(content=self.cible.mention, embed=embed, view=confirm_view)
        confirm_view.message = message

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True


pet_group = app_commands.Group(name="pet", description="Gère tes animaux capturés")


@pet_group.command(name="inventory", description="Affiche les animaux que tu as capturés")
async def pet_inventory_cmd(interaction: discord.Interaction):
    compteur = get_animal_counts(interaction.guild.id, interaction.user.id)

    if not compteur:
        await interaction.response.send_message("Tu n'as encore capturé aucun animal.", ephemeral=True)
        return

    lignes = []
    for nom, count in sorted(compteur.items(), key=lambda x: -x[1]):
        rarete = get_animal_rarete(nom)
        lignes.append(f"**{nom}** ({rarete}) x{count}")

    embed = discord.Embed(
        title=f"🐾 Inventaire de {interaction.user.display_name}",
        description="\n".join(lignes),
        color=discord.Color.blurple(),
    )
    embed.set_footer(text=f"{sum(compteur.values())} capture(s) au total")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@pet_group.command(name="trade", description="Propose un échange d'animal avec un autre membre")
@app_commands.describe(membre="Le membre avec qui échanger un animal")
async def pet_trade_cmd(interaction: discord.Interaction, membre: discord.Member):
    if membre.id == interaction.user.id:
        await interaction.response.send_message("❌ Tu ne peux pas échanger avec toi-même.", ephemeral=True)
        return
    if membre.bot:
        await interaction.response.send_message("❌ Tu ne peux pas échanger avec un bot.", ephemeral=True)
        return

    guild_conf = config.get(str(interaction.guild.id), {})
    collections = guild_conf.get("animal_collections", {})
    mes_animaux = collections.get(str(interaction.user.id), [])
    leurs_animaux = collections.get(str(membre.id), [])

    if not mes_animaux:
        await interaction.response.send_message("❌ Tu n'as aucun animal à échanger.", ephemeral=True)
        return
    if not leurs_animaux:
        await interaction.response.send_message(f"❌ {membre.mention} n'a aucun animal à échanger.", ephemeral=True)
        return

    view = PetTradeSetupView(interaction.user, membre, mes_animaux, leurs_animaux)
    await interaction.response.send_message(
        f"🔄 Configure ton échange avec {membre.mention} : choisis l'animal que tu proposes et celui que tu veux recevoir.",
        view=view,
        ephemeral=True,
    )


@pet_group.command(name="spawn", description="[Staff] Force l'apparition immédiate d'un animal sauvage")
async def pet_spawn_cmd(interaction: discord.Interaction):
    if not is_staff(interaction.user):
        await interaction.response.send_message(
            "❌ Tu n'as pas la permission d'utiliser cette commande.", ephemeral=True
        )
        return

    guild_conf = config.get(str(interaction.guild.id), {})
    animal_conf = guild_conf.get("animal_config")
    if not animal_conf or not animal_conf.get("channel_id"):
        await interaction.response.send_message(
            "❌ Le système d'animaux n'est pas configuré. Utilise `/animal config` d'abord.", ephemeral=True
        )
        return

    channel = interaction.guild.get_channel(animal_conf["channel_id"])
    if channel is None:
        await interaction.response.send_message("❌ Le salon configuré est introuvable.", ephemeral=True)
        return

    await interaction.response.send_message(f"✅ Un animal va apparaître dans {channel.mention} !", ephemeral=True)
    await spawn_animal(interaction.guild, channel)


bot.tree.add_command(pet_group)
 
 
# ================================================================
#           PANNEAU D'ADMINISTRATION (/admin panel)
# ================================================================
#
# Panneau (visible uniquement par la personne qui l'ouvre) avec des boutons
# pour déclencher des événements liés au système d'animaux : un boost de
# chance temporaire et l'apparition de plusieurs animaux d'un coup.

LUCK_BOOST_MULTIPLIER = 10
LUCK_BOOST_DURATION_SECONDS = 90  # 1 min 30
MASS_SPAWN_COUNT = 10
MASS_SPAWN_DELAY_SECONDS = 1.5  # petite pause entre chaque spawn pour ne pas saturer le salon


class AdminPanelView(discord.ui.View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=180)
        self.guild_id = guild_id

    @discord.ui.button(label="🍀 Luck x10 (1 min 30)", style=discord.ButtonStyle.success)
    async def luck_boost(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_staff(interaction.user):
            await interaction.response.send_message(
                "❌ Tu n'as pas la permission d'utiliser ce panneau.", ephemeral=True
            )
            return

        LUCK_BOOST[self.guild_id] = {
            "multiplier": LUCK_BOOST_MULTIPLIER,
            "expires_at": datetime.now(PARIS_TZ) + timedelta(seconds=LUCK_BOOST_DURATION_SECONDS),
        }

        await interaction.response.send_message(
            f"🍀 Chance x{LUCK_BOOST_MULTIPLIER} activée pendant {LUCK_BOOST_DURATION_SECONDS // 60} min "
            f"{LUCK_BOOST_DURATION_SECONDS % 60} s !",
            ephemeral=True,
        )

        guild_conf = config.get(str(self.guild_id), {})
        animal_conf = guild_conf.get("animal_config")
        if animal_conf and animal_conf.get("channel_id"):
            channel = interaction.guild.get_channel(animal_conf["channel_id"])
            if channel:
                try:
                    await channel.send(
                        "🍀✨ **ÉVÉNEMENT CHANCE x10 !** Pendant 1 min 30, les animaux rares ont bien plus "
                        "de chances d'apparaître. Restez à l'affût 👀"
                    )
                except discord.HTTPException:
                    pass

    @discord.ui.button(label="✨ Spawn x10", style=discord.ButtonStyle.primary)
    async def spawn_ten(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_staff(interaction.user):
            await interaction.response.send_message(
                "❌ Tu n'as pas la permission d'utiliser ce panneau.", ephemeral=True
            )
            return

        guild_conf = config.get(str(self.guild_id), {})
        animal_conf = guild_conf.get("animal_config")
        if not animal_conf or not animal_conf.get("channel_id"):
            await interaction.response.send_message(
                "❌ Le système d'animaux n'est pas configuré. Utilise `/animal config` d'abord.", ephemeral=True
            )
            return

        channel = interaction.guild.get_channel(animal_conf["channel_id"])
        if channel is None:
            await interaction.response.send_message("❌ Le salon configuré est introuvable.", ephemeral=True)
            return

        await interaction.response.send_message(
            f"✨ {MASS_SPAWN_COUNT} animaux vont apparaître dans {channel.mention} !", ephemeral=True
        )
        for _ in range(MASS_SPAWN_COUNT):
            try:
                await spawn_animal(interaction.guild, channel)
            except discord.HTTPException:
                pass
            await asyncio.sleep(MASS_SPAWN_DELAY_SECONDS)


admin_group = app_commands.Group(name="admin", description="Commandes d'administration du bot")


@admin_group.command(name="panel", description="[Staff] Ouvre le panneau d'administration (boost de chance, spawns multiples...)")
async def admin_panel_cmd(interaction: discord.Interaction):
    if not is_staff(interaction.user):
        await interaction.response.send_message(
            "❌ Tu n'as pas la permission d'utiliser cette commande.", ephemeral=True
        )
        return

    embed = discord.Embed(
        title="🛠️ Panneau d'administration",
        description=(
            "**🍀 Luck x10 (1 min 30)** — multiplie par 10 les chances des raretés autres que "
            "Membre pendant 1 min 30.\n"
            "**✨ Spawn x10** — fait apparaître 10 animaux d'un coup dans le salon configuré."
        ),
        color=discord.Color.dark_gold(),
    )
    view = AdminPanelView(interaction.guild.id)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


bot.tree.add_command(admin_group)
 
 
# ================================================================
#           MODE MAINTENANCE (/maintenance serveur)
# ================================================================
#
# Réservé au PROPRIÉTAIRE du serveur (guild.owner_id), pas seulement aux
# administrateurs. Bascule (toggle) : la première utilisation verrouille
# tous les salons pour @everyone (seul le staff garde l'accès), la
# deuxième utilisation restaure l'état précédent.

MAINTENANCE_ACTION_DELAY_SECONDS = 0.5  # petite pause entre chaque salon pour éviter le rate-limit Discord


def is_server_owner(interaction: discord.Interaction) -> bool:
    return interaction.guild is not None and interaction.guild.owner_id == interaction.user.id


async def activer_maintenance(guild: discord.Guild) -> dict:
    """Rend tous les salons invisibles pour @everyone (le staff garde l'accès).
    Retourne un dict {channel_id: ancienne_valeur_view_channel} pour pouvoir restaurer plus tard."""
    staff_role = discord.utils.get(guild.roles, name=STAFF_ROLE_NAME)
    sauvegarde = {}

    for channel in guild.channels:
        try:
            overwrite_everyone = channel.overwrites_for(guild.default_role)
            sauvegarde[str(channel.id)] = overwrite_everyone.view_channel  # True / False / None

            overwrite_everyone.view_channel = False
            await channel.set_permissions(guild.default_role, overwrite=overwrite_everyone, reason="Mode maintenance activé")

            if staff_role:
                overwrite_staff = channel.overwrites_for(staff_role)
                overwrite_staff.view_channel = True
                await channel.set_permissions(staff_role, overwrite=overwrite_staff, reason="Mode maintenance activé (accès staff)")
        except (discord.Forbidden, discord.HTTPException):
            pass
        await asyncio.sleep(MAINTENANCE_ACTION_DELAY_SECONDS)

    return sauvegarde


async def desactiver_maintenance(guild: discord.Guild, sauvegarde: dict) -> None:
    """Restaure la visibilité des salons telle qu'elle était avant l'activation."""
    for channel in guild.channels:
        try:
            valeur_precedente = sauvegarde.get(str(channel.id), "ABSENTE")
            overwrite_everyone = channel.overwrites_for(guild.default_role)
            overwrite_everyone.view_channel = None if valeur_precedente == "ABSENTE" else valeur_precedente
            await channel.set_permissions(guild.default_role, overwrite=overwrite_everyone, reason="Fin du mode maintenance")
        except (discord.Forbidden, discord.HTTPException):
            pass
        await asyncio.sleep(MAINTENANCE_ACTION_DELAY_SECONDS)


maintenance_group = app_commands.Group(name="maintenance", description="Active/désactive le mode maintenance du serveur")


@maintenance_group.command(
    name="serveur",
    description="[Propriétaire uniquement] Active/désactive le mode maintenance (salons privés sauf staff)",
)
async def maintenance_serveur_cmd(interaction: discord.Interaction):
    if not is_server_owner(interaction):
        await interaction.response.send_message(
            "❌ Seul le propriétaire du serveur peut utiliser cette commande.", ephemeral=True
        )
        return

    guild_conf = config.setdefault(str(interaction.guild.id), {})
    maintenance_conf = guild_conf.get("maintenance", {})

    await interaction.response.defer(ephemeral=True)

    if maintenance_conf.get("active"):
        await desactiver_maintenance(interaction.guild, maintenance_conf.get("saved_overwrites", {}))
        guild_conf["maintenance"] = {"active": False}
        save_config(config)
        await interaction.followup.send(
            "✅ Mode maintenance désactivé. Les salons ont retrouvé leur visibilité normale.", ephemeral=True
        )
    else:
        sauvegarde = await activer_maintenance(interaction.guild)
        guild_conf["maintenance"] = {"active": True, "saved_overwrites": sauvegarde}
        save_config(config)
        await interaction.followup.send(
            "🔒 Mode maintenance activé. Tous les salons sont désormais privés pour tout le monde, "
            "sauf pour le staff. Relance `/maintenance serveur` pour désactiver.",
            ephemeral=True,
        )


bot.tree.add_command(maintenance_group)
 
 
# ================================================================
#              SYSTÈME DE SOUTIENS (/soutiens)
# ================================================================
#
# /soutiens (staff) ouvre une fenêtre pour personnaliser un embed, puis (même
# principe que /ticketsetup : Discord n'autorise pas les menus déroulants
# dans une fenêtre) un menu déroulant listant tous les rôles pour choisir
# lequel attribuer automatiquement.
#
# Ensuite, dès qu'un membre met l'un des textes configurés (ex : "/akuma" ou
# ".gg/akuma") dans son STATUT PERSONNALISÉ Discord, le rôle lui est attribué
# automatiquement (et retiré s'il enlève ce texte de son statut).
#
# ⚠️ Ceci nécessite d'activer l'intent privilégié "Presence Intent" dans le
# Discord Developer Portal (onglet Bot de ton application), en plus des
# intents "Server Members" et "Message Content" déjà nécessaires. Sans ça,
# le bot ne recevra jamais les mises à jour de statut.

class SoutiensRoleSelectView(discord.ui.View):
    """Étape finale de /soutiens : menu déroulant natif listant tous les rôles
    du serveur, pour choisir lequel attribuer automatiquement."""

    def __init__(self, embed_data: dict, triggers_list: list):
        super().__init__(timeout=300)
        self.embed_data = embed_data
        self.triggers_list = triggers_list
        self._done = False

    @discord.ui.select(
        cls=discord.ui.RoleSelect,
        placeholder="Rôle à attribuer automatiquement",
        min_values=1,
        max_values=1,
    )
    async def role_select(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        if self._done:
            return
        self._done = True
        role = select.values[0]

        guild_conf = config.setdefault(str(interaction.guild.id), {})
        guild_conf["soutiens_config"] = {
            "role_id": role.id,
            "triggers": self.triggers_list,
            "titre": self.embed_data["titre"],
            "description": self.embed_data["description"],
        }
        save_config(config)

        embed = discord.Embed(
            title=self.embed_data["titre"],
            description=self.embed_data["description"],
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="✅ Comment obtenir le rôle",
            value=(
                "Mets l'un des textes suivants dans ton **statut personnalisé Discord** :\n"
                + "\n".join(f"`{t}`" for t in self.triggers_list)
            ),
            inline=False,
        )
        embed.set_footer(text=f"Rôle attribué automatiquement : {role.name}")

        self.stop()
        await interaction.response.edit_message(content="✅ Système de soutiens configuré et envoyé ci-dessous !", view=None)
        await interaction.channel.send(embed=embed)


class SoutiensSetupModal(discord.ui.Modal, title="Configuration du système de soutiens"):
    titre = discord.ui.TextInput(
        label="Titre de l'embed",
        placeholder="Ex : 🎉 Soutiens le serveur !",
        max_length=256,
    )
    description = discord.ui.TextInput(
        label="Description de l'embed",
        style=discord.TextStyle.paragraph,
        placeholder="Explique aux membres comment obtenir le rôle...",
        max_length=1000,
    )
    triggers = discord.ui.TextInput(
        label="Textes à détecter (1 par ligne)",
        style=discord.TextStyle.paragraph,
        placeholder="/akuma\n.gg/akuma",
        max_length=200,
    )

    async def on_submit(self, interaction: discord.Interaction):
        triggers_list = [t.strip() for t in self.triggers.value.splitlines() if t.strip()]
        if not triggers_list:
            await interaction.response.send_message(
                "❌ Indique au moins un texte à détecter dans le statut.", ephemeral=True
            )
            return

        embed_data = {"titre": self.titre.value, "description": self.description.value}
        await interaction.response.send_message(
            "🔧 Dernière étape : choisis le rôle à attribuer automatiquement aux membres qui mettent "
            + ", ".join(f"`{t}`" for t in triggers_list)
            + " dans leur statut.",
            view=SoutiensRoleSelectView(embed_data, triggers_list),
            ephemeral=True,
        )


@bot.tree.command(name="soutiens", description="[Staff] Configure et affiche le panneau des soutiens du serveur")
async def soutiens_cmd(interaction: discord.Interaction):
    if not is_staff(interaction.user):
        await interaction.response.send_message(
            "❌ Tu n'as pas la permission d'utiliser cette commande.", ephemeral=True
        )
        return
    await interaction.response.send_modal(SoutiensSetupModal())


@bot.event
async def on_presence_update(before: discord.Member, after: discord.Member):
    guild = after.guild
    if guild is None:
        return

    guild_conf = config.get(str(guild.id), {})
    soutiens_conf = guild_conf.get("soutiens_config")
    if not soutiens_conf:
        return

    role = guild.get_role(soutiens_conf.get("role_id"))
    if role is None:
        return

    triggers = [t.lower() for t in soutiens_conf.get("triggers", [])]
    if not triggers:
        return

    statut_texte = ""
    for activity in after.activities:
        if isinstance(activity, discord.CustomActivity) and activity.name:
            statut_texte = activity.name.lower()
            break

    correspond = any(trigger in statut_texte for trigger in triggers)
    a_deja_le_role = role in after.roles

    try:
        if correspond and not a_deja_le_role:
            await after.add_roles(role, reason="Statut de soutien détecté")
            print(f"[soutiens] Rôle '{role.name}' attribué à {after} sur {guild.name}.")
        elif not correspond and a_deja_le_role:
            await after.remove_roles(role, reason="Statut de soutien retiré")
            print(f"[soutiens] Rôle '{role.name}' retiré à {after} sur {guild.name}.")
    except discord.Forbidden:
        print(
            f"[soutiens] ❌ Permission refusée pour attribuer/retirer '{role.name}' à {after} sur {guild.name}. "
            "Vérifie que le rôle du bot est placé AU-DESSUS du rôle de soutien dans Paramètres du serveur → Rôles, "
            "et que le bot a bien la permission 'Gérer les rôles'."
        )
    except discord.HTTPException as e:
        print(f"[soutiens] ⚠️ Erreur HTTP lors de l'attribution du rôle à {after} : {e}")
 
# ================================================================
#           SYSTÈME DE BIENVENUE (/welcome config)
# ================================================================
#
# Système optionnel : /welcome config (staff) choisit le salon d'annonce et
# personnalise le message envoyé à chaque nouvel arrivant. Le message peut
# utiliser les variables suivantes :
#   {membre}          -> mentionne le nouveau membre
#   {pseudo}          -> pseudo du nouveau membre (sans mention)
#   {serveur}         -> nom du serveur
#   {nombre_membres}  -> nombre de membres sur le serveur après son arrivée
#
# Le système est désactivé tant qu'aucun salon n'a été configuré.
 
WELCOME_DEFAULT_MESSAGE = "👋 Bienvenue {membre} sur **{serveur}** ! Tu es notre {nombre_membres}e membres."
 
 
def get_welcome_config(guild_id: int) -> dict:
    return config.get(str(guild_id), {}).get("welcome_config", {})
 
 
def build_welcome_text(template: str, member: discord.Member) -> str:
    return (
        template.replace("{membre}", member.mention)
        .replace("{pseudo}", member.display_name)
        .replace("{serveur}", member.guild.name)
        .replace("{nombre_membres}", str(member.guild.member_count))
    )
 
 
welcome_group = app_commands.Group(name="welcome", description="Configuration du message de bienvenue (staff)")
 
 
@welcome_group.command(name="config", description="[Staff] Active/configure le message de bienvenue")
@app_commands.describe(
    salon="Salon où sera envoyé le message de bienvenue",
    message=(
        "Message personnalisé — variables dispo : {membre} {pseudo} {serveur} {nombre_membres}"
    ),
)
async def welcome_config_cmd(interaction: discord.Interaction, salon: discord.TextChannel, message: str = None):
    if not is_staff(interaction.user):
        await interaction.response.send_message(
            "❌ Tu n'as pas la permission d'utiliser cette commande.", ephemeral=True
        )
        return
 
    guild_conf = config.setdefault(str(interaction.guild.id), {})
    welcome_conf = guild_conf.setdefault("welcome_config", {})
    welcome_conf["channel_id"] = salon.id
    if message:
        welcome_conf["message"] = message
    save_config(config)
 
    apercu = build_welcome_text(welcome_conf.get("message") or WELCOME_DEFAULT_MESSAGE, interaction.user)
    await interaction.response.send_message(
        f"✅ Message de bienvenue activé dans {salon.mention} !\n\n**Aperçu :**\n{apercu}",
        ephemeral=True,
    )
 
 
@welcome_group.command(name="desactiver", description="[Staff] Désactive le message de bienvenue")
async def welcome_desactiver_cmd(interaction: discord.Interaction):
    if not is_staff(interaction.user):
        await interaction.response.send_message(
            "❌ Tu n'as pas la permission d'utiliser cette commande.", ephemeral=True
        )
        return
 
    guild_conf = config.setdefault(str(interaction.guild.id), {})
    if "welcome_config" in guild_conf:
        del guild_conf["welcome_config"]
        save_config(config)
 
    await interaction.response.send_message("✅ Message de bienvenue désactivé sur ce serveur.", ephemeral=True)
 
 
bot.tree.add_command(welcome_group)
 
 
async def send_welcome_message(member: discord.Member) -> None:
    welcome_conf = get_welcome_config(member.guild.id)
    channel_id = welcome_conf.get("channel_id")
    if not channel_id:
        return
 
    channel = member.guild.get_channel(channel_id)
    if channel is None:
        return
 
    template = welcome_conf.get("message") or WELCOME_DEFAULT_MESSAGE
    texte = build_welcome_text(template, member)
    try:
        await channel.send(texte)
    except discord.HTTPException:
        pass
 
# ================================================================
#                    SYSTÈME ANTI-FLOOD
# ================================================================
#
# Contrairement à l'anti-spam (même message répété), l'anti-flood surveille
# le NOMBRE de messages envoyés en peu de temps, peu importe leur contenu.
# Au-delà du seuil, le membre est automatiquement mute (timeout) quelques
# instants. Le staff n'est pas concerné par cette limite.

FLOOD_WINDOW_SECONDS = 5      # fenêtre de temps surveillée
FLOOD_THRESHOLD = 5           # nombre de messages autorisés dans cette fenêtre
FLOOD_TIMEOUT_SECONDS = 60    # durée du mute appliqué en cas de flood détecté

flood_tracker: dict[tuple[int, int], list] = {}  # (guild_id, user_id) -> liste d'horodatages récents


async def check_flood(message: discord.Message) -> None:
    if is_staff(message.author):
        return

    cle = (message.guild.id, message.author.id)
    maintenant = datetime.now(PARIS_TZ)
    horodatages = flood_tracker.setdefault(cle, [])
    horodatages.append(maintenant)

    seuil_temps = maintenant - timedelta(seconds=FLOOD_WINDOW_SECONDS)
    horodatages[:] = [t for t in horodatages if t >= seuil_temps]

    if len(horodatages) >= FLOOD_THRESHOLD:
        horodatages.clear()  # évite de re-déclencher immédiatement après le mute
        try:
            until = discord.utils.utcnow() + timedelta(seconds=FLOOD_TIMEOUT_SECONDS)
            await message.author.timeout(until, reason="Anti-flood : trop de messages envoyés trop rapidement")
            await message.channel.send(
                f"🚫 {message.author.mention} a été mute {FLOOD_TIMEOUT_SECONDS}s pour flood "
                "(trop de messages envoyés trop rapidement)."
            )
        except discord.Forbidden:
            try:
                await message.channel.send(
                    f"⚠️ {message.author.mention}, ralentis un peu — tu envoies des messages trop vite ! "
                    "(je n'ai pas pu te mute automatiquement, vérifie mes permissions)"
                )
            except discord.HTTPException:
                pass
        except discord.HTTPException:
            pass
 
 
 
# ================================================================
#                      +stats serveur
# ================================================================
 
async def get_or_create_stats_channels(guild: discord.Guild):
    category = discord.utils.get(guild.categories, name=STATS_CATEGORY_NAME)
    if category is None:
        category = await guild.create_category(STATS_CATEGORY_NAME)
 
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(connect=False, view_channel=True)
    }
 
    members_channel = discord.utils.find(lambda c: c.name.startswith("⌛️・Membre"), category.voice_channels)
    if members_channel is None:
        members_channel = await guild.create_voice_channel(
            f"⌛️・Membre : {guild.member_count}", category=category, overwrites=overwrites
        )
 
    bots_channel = discord.utils.find(lambda c: c.name.startswith("🩸・Bot"), category.voice_channels)
    if bots_channel is None:
        nb_bots = sum(1 for m in guild.members if m.bot)
        bots_channel = await guild.create_voice_channel(
            f"🩸・Bot : {nb_bots}", category=category, overwrites=overwrites
        )
 
    return members_channel, bots_channel
 
 
@bot.command(name="stats")
async def stats_command(ctx: commands.Context, sous_commande: str = None):
    if sous_commande is None or sous_commande.lower() != "serveur":
        await ctx.send("Utilise `+stats serveur` pour créer/actualiser les statistiques du serveur.")
        return
 
    if not is_staff(ctx.author):
        await ctx.send("❌ Cette commande est réservée au staff.")
        return
 
    await get_or_create_stats_channels(ctx.guild)
    await ctx.send("✅ Les salons de statistiques ont été créés / mis à jour.")
 
    if not update_stats_loop.is_running():
        update_stats_loop.start()
 
 
@tasks.loop(minutes=STATS_UPDATE_INTERVAL_MINUTES)
async def update_stats_loop():
    for guild in bot.guilds:
        category = discord.utils.get(guild.categories, name=STATS_CATEGORY_NAME)
        if category is None:
            continue
 
        nb_members = guild.member_count
        nb_bots = sum(1 for m in guild.members if m.bot)
 
        members_channel = discord.utils.find(lambda c: c.name.startswith("⌛️・Membre"), category.voice_channels)
        bots_channel = discord.utils.find(lambda c: c.name.startswith("🩸・Bot"), category.voice_channels)
 
        try:
            if members_channel and not members_channel.name.endswith(f": {nb_members}"):
                await members_channel.edit(name=f"⌛️・Membre : {nb_members}")
            if bots_channel and not bots_channel.name.endswith(f": {nb_bots}"):
                await bots_channel.edit(name=f"🩸・Bot : {nb_bots}")
        except discord.HTTPException:
            pass
 
 
# ================================================================
#                  /setrole absences [rôle]
# ================================================================
 
@bot.tree.command(name="setrole", description="Autorise un rôle à valider une catégorie (ex: absences)")
@app_commands.describe(categorie="Catégorie concernée", role="Rôle autorisé à valider")
@app_commands.choices(categorie=[app_commands.Choice(name="absences", value="absences")])
async def setrole(interaction: discord.Interaction, categorie: app_commands.Choice[str], role: discord.Role):
    if not is_staff(interaction.user):
        await interaction.response.send_message(
            "❌ Tu n'as pas la permission d'utiliser cette commande.", ephemeral=True
        )
        return
 
    add_validator_role(interaction.guild.id, categorie.value, role.id)
    await interaction.response.send_message(
        f"✅ Le rôle {role.mention} peut désormais valider les **{categorie.value}**.", ephemeral=True
    )
 
# ================================================================
#                  /set updatelogs [salon]
# ================================================================
#
# Envoie (et mémorise) le salon où sont publiées les nouveautés du bot.
# Pour ajouter une nouvelle entrée au changelog, il suffit de compléter
# la liste UPDATE_LOGS ci-dessous.

UPDATE_LOGS = [
    {
        "titre": "🎫 Système de tickets",
        "description": (
            "Ajout de `/ticketsetup` : crée un panneau de tickets entièrement personnalisable "
            "(titre, texte, boutons de couleurs, rôle(s) à ping) directement depuis une fenêtre Discord.\n"
            "Chaque bouton ouvre un salon privé pour l'utilisateur, avec un bouton pour fermer le ticket."
        ),
    },
    {
        "titre": "👑 Élu de la semaine",
        "description": (
            "Chaque dimanche à 00h30 (heure de Paris), le membre ayant envoyé le plus de messages "
            "dans la semaine reçoit automatiquement le rôle **👑 Élu de la semaine** pendant 7 jours.\n"
            "Commandes : `/eludelasemaine` (affiche les règles) et `/forcerelu` (force la sélection, staff)."
        ),
    },
    {
        "titre": "🎂 Système d'anniversaires",
        "description": (
            "Système optionnel : `/anniv config` (staff) active les annonces d'anniversaire dans un salon.\n"
            "Les membres enregistrent leur date avec `/anniversaire create` (jour/mois uniquement, sans année)."
        ),
    },
    {
        "titre": "📱 Notifications TikTok",
        "description": (
            "`/config tiktok` (staff) permet de recevoir une notification à chaque nouvelle vidéo "
            "du compte TikTok suivi."
        ),
    },
    {
        "titre": "🐾 Animaux à capturer",
        "description": (
            "Système optionnel : `/animal config` (staff) fait apparaître un animal sauvage par jour, "
            "à une heure aléatoire. Premier arrivé, premier servi ! Voir sa collection avec `/animal collection`."
        ),
    },
]


def build_updatelogs_embed() -> discord.Embed:
    embed = discord.Embed(
        title="📢 Nouveautés du bot",
        description="Voici les dernières fonctionnalités ajoutées au bot :",
        color=discord.Color.blurple(),
        timestamp=datetime.utcnow(),
    )
    for item in UPDATE_LOGS:
        embed.add_field(name=item["titre"], value=item["description"], inline=False)
    embed.set_footer(text="Mises à jour du bot")
    return embed


set_group = app_commands.Group(name="set", description="Commandes de configuration du bot")


@set_group.command(name="updatelogs", description="[Staff] Définit le salon des nouveautés du bot et y publie le changelog")
@app_commands.describe(salon="Salon où seront envoyées les nouveautés du bot")
async def set_updatelogs(interaction: discord.Interaction, salon: discord.TextChannel):
    if not is_staff(interaction.user):
        await interaction.response.send_message(
            "❌ Tu n'as pas la permission d'utiliser cette commande.", ephemeral=True
        )
        return

    guild_conf = config.setdefault(str(interaction.guild.id), {})
    guild_conf["updatelogs_channel_id"] = salon.id
    save_config(config)

    embed = build_updatelogs_embed()
    try:
        await salon.send(embed=embed)
    except discord.Forbidden:
        await interaction.response.send_message(
            f"❌ Je n'ai pas la permission d'envoyer de message dans {salon.mention}.", ephemeral=True
        )
        return
    except discord.HTTPException:
        await interaction.response.send_message(
            "❌ Erreur lors de l'envoi des nouveautés dans le salon.", ephemeral=True
        )
        return

    await interaction.response.send_message(
        f"✅ Le salon des nouveautés a été défini sur {salon.mention} et le changelog y a été envoyé.",
        ephemeral=True,
    )


bot.tree.add_command(set_group)

# ================================================================
#                       +invite-stats
# ================================================================
 
invites_cache: dict[int, dict[str, int]] = {}  # {guild_id: {invite_code: uses}}
 
 
async def update_invites_cache(guild: discord.Guild) -> None:
    try:
        invites = await guild.invites()
        invites_cache[guild.id] = {invite.code: invite.uses for invite in invites}
    except discord.Forbidden:
        invites_cache[guild.id] = {}
 
 
@bot.event
async def on_member_join(member: discord.Member):
    guild = member.guild
    old_invites = invites_cache.get(guild.id, {})
 
    try:
        new_invites = await guild.invites()
    except discord.Forbidden:
        return
 
    inviter = None
    for invite in new_invites:
        if invite.uses > old_invites.get(invite.code, 0):
            inviter = invite.inviter
            break
 
    invites_cache[guild.id] = {invite.code: invite.uses for invite in new_invites}
 
    if inviter is not None:
        guild_conf = config.setdefault(str(guild.id), {})
        invite_stats = guild_conf.setdefault("invite_stats", {})
        invite_stats[str(inviter.id)] = invite_stats.get(str(inviter.id), 0) + 1
        save_config(config)
 
 
@bot.event
async def on_guild_join(guild: discord.Guild):
    await update_invites_cache(guild)
 
 
@bot.command(name="invite-stats")
async def invite_stats_command(ctx: commands.Context, membre: discord.Member = None):
    membre = membre or ctx.author
    invite_stats = config.get(str(ctx.guild.id), {}).get("invite_stats", {})
    count = invite_stats.get(str(membre.id), 0)
 
    embed = discord.Embed(
        title="📊 Statistiques d'invitations",
        description=f"{membre.mention} a invité **{count}** membre(s) sur ce serveur.",
        color=discord.Color.gold(),
    )
    embed.set_thumbnail(url=membre.display_avatar.url)
    await ctx.send(embed=embed)
 
 
# ================================================================
#                         +concept
# ================================================================
 
def get_concept_list(guild_id: int) -> list:
    return config.get(str(guild_id), {}).get("concept_list", [])
 
 
def save_concept_list(guild_id: int, members: list) -> None:
    guild_conf = config.setdefault(str(guild_id), {})
    guild_conf["concept_list"] = members
    save_config(config)
 
 
@bot.command(name="concept")
async def concept_command(ctx: commands.Context, sous_commande: str = None, membre: discord.Member = None):
    if sous_commande and sous_commande.lower() == "list":
 
        if membre is not None:
            await ctx.send("❌ Utilise `+concept list reset` pour réinitialiser la liste.")
            return
 
        concept_list = get_concept_list(ctx.guild.id)
 
        if not concept_list:
            embed = discord.Embed(
                title="📋 Liste Concept",
                description="Aucun membre n'est actuellement dans la liste.",
                color=discord.Color.blurple()
            )
            await ctx.send(embed=embed)
            return
 
        mentions = []
        for user_id in concept_list:
            member = ctx.guild.get_member(int(user_id))
            if member:
                mentions.append(f"• {member.mention}")
            else:
                mentions.append(f"• <@{user_id}>")
 
        embed = discord.Embed(
            title="📋 Liste Concept",
            description="\n".join(mentions),
            color=discord.Color.blurple()
        )
        embed.set_footer(text=f"{len(concept_list)} membre(s) dans la liste.")
        await ctx.send(embed=embed)
        return
 
    if sous_commande and sous_commande.lower() == "note":
 
        if not is_staff(ctx.author):
            await ctx.send("❌ Cette commande est réservée au staff.")
            return
 
        if membre is None:
            await ctx.send("❌ Utilise `+concept note @membre`.")
            return
 
        concept_list = get_concept_list(ctx.guild.id)
 
        if str(membre.id) in concept_list:
            await ctx.send(f"⚠️ {membre.mention} est déjà dans la liste Concept.")
            return
 
        concept_list.append(str(membre.id))
        save_concept_list(ctx.guild.id, concept_list)
 
        await ctx.send(f"✅ {membre.mention} a été ajouté à la **liste Concept**.")
        return
 
    await ctx.send(
        "❌ Utilisation :\n"
        "`+concept note @membre` — Ajouter un membre (Staff)\n"
        "`+concept list` — Voir la liste\n"
        "`+concept list reset` — Réinitialiser la liste (Staff)"
    )
 
 
# ================================================================
#                    ÉLU DE LA SEMAINE
# ================================================================
 
def get_weekly_counts(guild_id: int) -> dict:
    return config.get(str(guild_id), {}).get("weekly_counts", {})
 
 
def bump_weekly_count(guild_id: int, user_id: int) -> None:
    guild_conf = config.setdefault(str(guild_id), {})
    weekly = guild_conf.setdefault("weekly_counts", {})
    uid = str(user_id)
    weekly[uid] = weekly.get(uid, 0) + 1
    save_config(config)
 
 
def get_elu_actuel(guild_id: int):
    return config.get(str(guild_id), {}).get("elu_actuel")
 
 
async def get_or_create_elu_role(guild: discord.Guild) -> discord.Role | None:
    role = discord.utils.get(guild.roles, name=ELU_ROLE_NAME)
    if role is None:
        try:
            role = await guild.create_role(
                name=ELU_ROLE_NAME,
                color=discord.Color.gold(),
                reason="Création automatique du rôle Élu de la semaine",
            )
        except discord.HTTPException:
            role = None
    return role
 
 
def build_elu_embed(guild: discord.Guild | None = None) -> discord.Embed:
    """Construit l'embed de présentation, dans le même esprit que la capture d'écran."""
    embed = discord.Embed(
        title="👑 • ÉLU DE LA SEMAINE",
        color=discord.Color.from_rgb(20, 20, 24),
    )
    embed.set_image(url=ELU_GIF_URL)
    embed.add_field(
        name="🏆 LE PRINCIPE",
        value=(
            "Chaque semaine, les messages envoyés dans le chat sont comptabilisés.\n\n"
            "Chaque **dimanche à 00h30**, le membre ayant envoyé le plus de messages "
            "devient l'**Élu de la semaine**.\n\n"
            f"👑 Il reçoit le rôle **{ELU_ROLE_NAME}** pendant 7 jours.\n"
            "🔄 Lors de la prochaine sélection, l'ancien rôle est retiré et attribué "
            "au nouveau gagnant.\n"
            "📅 Sélection : dimanche à 00h30 — heure de Paris\n"
            "💬 Seul le chat de la semaine est pris en compte."
        ),
        inline=False,
    )
 
    if guild is not None:
        current_id = get_elu_actuel(guild.id)
        if current_id:
            member = guild.get_member(int(current_id))
            mention = member.mention if member else f"<@{current_id}>"
            embed.add_field(name="👑 Élu actuel", value=mention, inline=False)
        else:
            embed.add_field(name="👑 Élu actuel", value="Aucun élu pour le moment.", inline=False)
 
    return embed
 
 
@bot.tree.command(name="eludelasemaine", description="Affiche les règles de l'Élu de la semaine")
async def eludelasemaine(interaction: discord.Interaction):
    if not is_staff(interaction.user):
        await interaction.response.send_message(
            "❌ Tu n'as pas la permission d'utiliser cette commande.", ephemeral=True
        )
        return
 
    embed = build_elu_embed(interaction.guild)
    await interaction.response.send_message(embed=embed)
 
 
@bot.tree.command(name="forcerelu", description="[Staff] Force la sélection immédiate de l'Élu de la semaine")
async def forcerelu(interaction: discord.Interaction):
    if not is_staff(interaction.user):
        await interaction.response.send_message(
            "❌ Tu n'as pas la permission d'utiliser cette commande.", ephemeral=True
        )
        return
 
    await interaction.response.defer(ephemeral=True)
    await select_elu_semaine(interaction.guild)
    await interaction.followup.send("✅ La sélection de l'Élu de la semaine a été forcée.", ephemeral=True)
 
 
async def select_elu_semaine(guild: discord.Guild) -> None:
    """Sélectionne le membre ayant le plus parlé cette semaine, échange le rôle, reset les compteurs."""
    guild_conf = config.setdefault(str(guild.id), {})
    weekly = guild_conf.get("weekly_counts", {})
 
    role = await get_or_create_elu_role(guild)
 
    # Retire le rôle à l'ancien élu
    ancien_id = guild_conf.get("elu_actuel")
    if role and ancien_id:
        ancien_membre = guild.get_member(int(ancien_id))
        if ancien_membre:
            try:
                await ancien_membre.remove_roles(role, reason="Fin de règne - Élu de la semaine")
            except discord.HTTPException:
                pass
 
    if not weekly:
        guild_conf["elu_actuel"] = None
        guild_conf["weekly_counts"] = {}
        save_config(config)
        return
 
    gagnant_id = max(weekly, key=weekly.get)
    gagnant_membre = guild.get_member(int(gagnant_id))
 
    if role and gagnant_membre:
        try:
            await gagnant_membre.add_roles(role, reason="Élu de la semaine")
        except discord.HTTPException:
            pass
 
    channel = guild.system_channel or discord.utils.get(guild.text_channels, name="général")
    if channel and gagnant_membre:
        try:
            await channel.send(
                content=f"🎉 Félicitations {gagnant_membre.mention}, tu es l'**Élu de la semaine** !",
                embed=build_elu_embed(guild),
            )
        except discord.HTTPException:
            pass
 
    guild_conf["elu_actuel"] = gagnant_id
    guild_conf["weekly_counts"] = {}
    save_config(config)
 
 
@tasks.loop(minutes=1)
async def check_elu_semaine():
    now = datetime.now(PARIS_TZ)
    # weekday() == 6 -> dimanche
    if now.weekday() == 6 and now.hour == 0 and now.minute == 30:
        for guild in bot.guilds:
            await select_elu_semaine(guild)
 
 
@check_elu_semaine.before_loop
async def before_check_elu_semaine():
    await bot.wait_until_ready()
 
 
@bot.tree.command(name="clear", description="[Staff] Supprime un nombre de messages dans le salon")
@app_commands.describe(nombre="Nombre de messages à supprimer (1 à 100)")
async def clear(interaction: discord.Interaction, nombre: app_commands.Range[int, 1, 100]):
    if not is_staff(interaction.user):
        await interaction.response.send_message(
            "❌ Tu n'as pas la permission d'utiliser cette commande.", ephemeral=True
        )
        return
 
    await interaction.response.defer(ephemeral=True)
    try:
        supprimes = await interaction.channel.purge(limit=nombre)
    except discord.Forbidden:
        await interaction.followup.send(
            "❌ Je n'ai pas la permission de supprimer des messages dans ce salon.", ephemeral=True
        )
        return
    except discord.HTTPException:
        await interaction.followup.send(
            "❌ Erreur lors de la suppression des messages (les messages de plus de 14 jours ne peuvent pas être supprimés en masse).",
            ephemeral=True,
        )
        return
 
    await interaction.followup.send(f"✅ {len(supprimes)} message(s) supprimé(s).", ephemeral=True)
 
 
# ================================================================
#                       MODÉRATION
# ================================================================
 
def get_warns(guild_id: int, user_id: int) -> list:
    return config.get(str(guild_id), {}).get("warns", {}).get(str(user_id), [])
 
 
def add_warn(guild_id: int, user_id: int, moderator_id: int, raison: str) -> int:
    guild_conf = config.setdefault(str(guild_id), {})
    warns = guild_conf.setdefault("warns", {})
    user_warns = warns.setdefault(str(user_id), [])
    user_warns.append({
        "reason": raison,
        "moderator_id": str(moderator_id),
        "date": datetime.utcnow().isoformat(),
    })
    save_config(config)
    return len(user_warns)
 
 
@bot.command(name="warn")
async def warn_command(ctx: commands.Context, cible: str = None, *, reste: str = None):
    if not is_staff(ctx.author):
        await ctx.send("❌ Cette commande est réservée au staff.")
        return
 
    if cible is None:
        await ctx.send(
            "❌ Utilisation :\n"
            "`+warn @membre <raison>` — Avertir un membre\n"
            "`+warn list @membre` — Voir ses avertissements"
        )
        return
 
    # ---- +warn list @membre ----
    if cible.lower() == "list":
        if reste is None:
            await ctx.send("❌ Utilise `+warn list @membre`.")
            return
        try:
            membre = await commands.MemberConverter().convert(ctx, reste.strip())
        except commands.MemberNotFound:
            await ctx.send("❌ Membre introuvable.")
            return
 
        warns = get_warns(ctx.guild.id, membre.id)
        if not warns:
            embed = discord.Embed(
                title=f"📋 Avertissements de {membre.display_name}",
                description="Aucun avertissement.",
                color=discord.Color.green(),
            )
        else:
            lignes = []
            for i, w in enumerate(warns, start=1):
                date = w["date"][:10]
                mod = ctx.guild.get_member(int(w["moderator_id"]))
                mod_nom = mod.mention if mod else f"<@{w['moderator_id']}>"
                lignes.append(f"**#{i}** — {w['reason']} *(par {mod_nom}, le {date})*")
            embed = discord.Embed(
                title=f"📋 Avertissements de {membre.display_name}",
                description="\n".join(lignes),
                color=discord.Color.orange(),
            )
        embed.set_footer(text=f"{len(warns)} avertissement(s)")
        embed.set_thumbnail(url=membre.display_avatar.url)
        await ctx.send(embed=embed)
        return
 
    # ---- +warn @membre <raison> ----
    try:
        membre = await commands.MemberConverter().convert(ctx, cible)
    except commands.MemberNotFound:
        await ctx.send("❌ Membre introuvable.")
        return
 
    raison = reste or "Aucune raison précisée."
    total = add_warn(ctx.guild.id, membre.id, ctx.author.id, raison)
 
    embed = discord.Embed(title="⚠️ Avertissement", color=discord.Color.orange())
    embed.add_field(name="Membre", value=membre.mention, inline=True)
    embed.add_field(name="Modérateur", value=ctx.author.mention, inline=True)
    embed.add_field(name="Raison", value=raison, inline=False)
    embed.set_footer(text=f"{membre.display_name} a désormais {total} avertissement(s).")
    await ctx.send(embed=embed)
 
    try:
        await membre.send(
            f"⚠️ Tu as reçu un avertissement sur **{ctx.guild.name}**.\nRaison : {raison}"
        )
    except discord.HTTPException:
        pass
 
 
def parse_duration(duree_str: str):
    """Convertit '10m', '2h', '1j'/'1d', '30s' en secondes. Retourne None si invalide."""
    unites = {"s": 1, "m": 60, "h": 3600, "j": 86400, "d": 86400}
    if not duree_str or len(duree_str) < 2:
        return None
    unite = duree_str[-1].lower()
    if unite not in unites:
        return None
    try:
        valeur = int(duree_str[:-1])
    except ValueError:
        return None
    if valeur <= 0:
        return None
    return valeur * unites[unite]
 
 
@bot.command(name="mute")
async def mute_command(ctx: commands.Context, membre: discord.Member = None, duree: str = None, *, raison: str = None):
    if not is_staff(ctx.author):
        await ctx.send("❌ Cette commande est réservée au staff.")
        return
 
    if membre is None or duree is None:
        await ctx.send("❌ Utilisation : `+mute @membre <durée ex: 10m/2h/1j> [raison]`")
        return
 
    secondes = parse_duration(duree)
    if secondes is None:
        await ctx.send("❌ Durée invalide. Utilise un format comme `10m`, `2h`, `1j`.")
        return
 
    secondes = min(secondes, 28 * 86400)  # Discord limite le timeout à 28 jours max
    raison = raison or "Aucune raison précisée."
    until = discord.utils.utcnow() + timedelta(seconds=secondes)
 
    try:
        await membre.timeout(until, reason=f"{raison} (par {ctx.author})")
    except discord.Forbidden:
        await ctx.send("❌ Je n'ai pas la permission de mute ce membre (vérifie la position de mon rôle).")
        return
    except discord.HTTPException:
        await ctx.send("❌ Erreur lors du mute.")
        return
 
    embed = discord.Embed(title="🔇 Membre mute", color=discord.Color.dark_grey())
    embed.add_field(name="Membre", value=membre.mention, inline=True)
    embed.add_field(name="Durée", value=duree, inline=True)
    embed.add_field(name="Raison", value=raison, inline=False)
    embed.set_footer(text=f"Par {ctx.author}")
    await ctx.send(embed=embed)
 
    try:
        await membre.send(
            f"🔇 Tu as été rendu muet sur **{ctx.guild.name}** pour {duree}.\nRaison : {raison}"
        )
    except discord.HTTPException:
        pass
 
 
@bot.command(name="unmute")
async def unmute_command(ctx: commands.Context, membre: discord.Member = None):
    if not is_staff(ctx.author):
        await ctx.send("❌ Cette commande est réservée au staff.")
        return
 
    if membre is None:
        await ctx.send("❌ Utilisation : `+unmute @membre`")
        return
 
    try:
        await membre.timeout(None, reason=f"Unmute par {ctx.author}")
    except discord.Forbidden:
        await ctx.send("❌ Je n'ai pas la permission de unmute ce membre.")
        return
    except discord.HTTPException:
        await ctx.send("❌ Erreur lors du unmute.")
        return
 
    await ctx.send(f"🔊 {membre.mention} n'est plus mute.")
 
 
# ================================================================
#              SYSTÈME DE SIGNALEMENT (/report)
# ================================================================
#
# Permet à n'importe quel membre de signaler discrètement un autre membre
# au staff. Le signalement part directement dans un salon privé (visible
# uniquement par le staff), jamais publiquement dans le salon où la commande
# est utilisée.

def get_report_channel_id(guild_id: int):
    return config.get(str(guild_id), {}).get("report_config", {}).get("channel_id")


def add_report(guild_id: int, reporter_id: int, target_id: int, raison: str) -> None:
    guild_conf = config.setdefault(str(guild_id), {})
    reports = guild_conf.setdefault("reports", {})
    target_reports = reports.setdefault(str(target_id), [])
    target_reports.append({
        "reporter_id": str(reporter_id),
        "reason": raison,
        "date": datetime.utcnow().isoformat(),
    })
    save_config(config)


def get_reports(guild_id: int, target_id: int) -> list:
    return config.get(str(guild_id), {}).get("reports", {}).get(str(target_id), [])


report_group = app_commands.Group(name="report", description="Signale un membre au staff (discrètement)")


@report_group.command(name="config", description="[Staff] Définit le salon où arrivent les signalements")
@app_commands.describe(salon="Salon privé (visible seulement par le staff) où seront envoyés les signalements")
async def report_config_cmd(interaction: discord.Interaction, salon: discord.TextChannel):
    if not is_staff(interaction.user):
        await interaction.response.send_message(
            "❌ Tu n'as pas la permission d'utiliser cette commande.", ephemeral=True
        )
        return

    guild_conf = config.setdefault(str(interaction.guild.id), {})
    report_conf = guild_conf.setdefault("report_config", {})
    report_conf["channel_id"] = salon.id
    save_config(config)

    await interaction.response.send_message(
        f"✅ Les signalements seront désormais envoyés dans {salon.mention}. "
        "Pense à vérifier que ce salon n'est visible que par le staff !",
        ephemeral=True,
    )


@report_group.command(name="envoyer", description="Signale un membre au staff (discret, personne d'autre ne le voit)")
@app_commands.describe(membre="Le membre à signaler", raison="Explique la raison du signalement")
async def report_envoyer_cmd(interaction: discord.Interaction, membre: discord.Member, raison: str):
    if membre.id == interaction.user.id:
        await interaction.response.send_message("❌ Tu ne peux pas te signaler toi-même.", ephemeral=True)
        return
    if membre.bot:
        await interaction.response.send_message("❌ Tu ne peux pas signaler un bot.", ephemeral=True)
        return

    channel_id = get_report_channel_id(interaction.guild.id)
    if not channel_id:
        await interaction.response.send_message(
            "❌ Le système de signalement n'est pas configuré sur ce serveur. Un membre du staff doit "
            "utiliser `/report config` d'abord.",
            ephemeral=True,
        )
        return

    channel = interaction.guild.get_channel(channel_id)
    if channel is None:
        await interaction.response.send_message(
            "❌ Le salon de signalement configuré est introuvable. Contacte le staff.", ephemeral=True
        )
        return

    add_report(interaction.guild.id, interaction.user.id, membre.id, raison)

    embed = discord.Embed(
        title="🚩 Nouveau signalement",
        color=discord.Color.orange(),
        timestamp=datetime.utcnow(),
    )
    embed.add_field(name="Membre signalé", value=f"{membre.mention} ({membre})", inline=False)
    embed.add_field(name="Signalé par", value=f"{interaction.user.mention} ({interaction.user})", inline=False)
    embed.add_field(name="Raison", value=raison, inline=False)
    embed.add_field(name="Salon d'origine", value=interaction.channel.mention if interaction.channel else "—", inline=False)

    try:
        await channel.send(embed=embed)
    except discord.Forbidden:
        await interaction.response.send_message(
            "❌ Je n'ai pas la permission d'écrire dans le salon de signalement configuré.", ephemeral=True
        )
        return
    except discord.HTTPException:
        await interaction.response.send_message("❌ Erreur lors de l'envoi du signalement.", ephemeral=True)
        return

    await interaction.response.send_message(
        "✅ Ton signalement a bien été envoyé au staff. Merci de nous aider à garder le serveur sain !",
        ephemeral=True,
    )


@report_group.command(name="historique", description="[Staff] Affiche les signalements reçus contre un membre")
@app_commands.describe(membre="Le membre dont tu veux voir l'historique des signalements")
async def report_historique_cmd(interaction: discord.Interaction, membre: discord.Member):
    if not is_staff(interaction.user):
        await interaction.response.send_message(
            "❌ Tu n'as pas la permission d'utiliser cette commande.", ephemeral=True
        )
        return

    reports = get_reports(interaction.guild.id, membre.id)
    if not reports:
        embed = discord.Embed(
            title=f"🚩 Signalements de {membre.display_name}",
            description="Aucun signalement.",
            color=discord.Color.green(),
        )
    else:
        lignes = []
        for i, r in enumerate(reports, start=1):
            date = r["date"][:10]
            reporter = interaction.guild.get_member(int(r["reporter_id"]))
            nom_reporter = reporter.mention if reporter else f"<@{r['reporter_id']}>"
            lignes.append(f"**#{i}** — {r['reason']} *(signalé par {nom_reporter}, le {date})*")
        embed = discord.Embed(
            title=f"🚩 Signalements de {membre.display_name}",
            description="\n".join(lignes),
            color=discord.Color.orange(),
        )
    embed.set_footer(text=f"{len(reports)} signalement(s)")
    embed.set_thumbnail(url=membre.display_avatar.url)
    await interaction.response.send_message(embed=embed, ephemeral=True)


bot.tree.add_command(report_group)
 
 
# ---------------- +add role / +remove role ----------------
 
@bot.group(name="add", invoke_without_command=True)
async def add_group(ctx: commands.Context):
    await ctx.send("❌ Utilise `+add role @membre @role`.")
 
 
@add_group.command(name="role")
async def add_role_cmd(ctx: commands.Context, membre: discord.Member, *, role: discord.Role):
    if not is_staff(ctx.author):
        await ctx.send("❌ Cette commande est réservée au staff.")
        return
 
    if role >= ctx.guild.me.top_role:
        await ctx.send("❌ Je ne peux pas attribuer un rôle égal ou supérieur à mon rôle le plus haut.")
        return
 
    try:
        await membre.add_roles(role, reason=f"Ajouté par {ctx.author}")
    except discord.Forbidden:
        await ctx.send("❌ Permissions insuffisantes pour ajouter ce rôle.")
        return
    except discord.HTTPException:
        await ctx.send("❌ Erreur lors de l'ajout du rôle.")
        return
 
    await ctx.send(f"✅ Le rôle {role.mention} a été ajouté à {membre.mention}.")
 
 
@bot.group(name="remove", invoke_without_command=True)
async def remove_group(ctx: commands.Context):
    await ctx.send("❌ Utilise `+remove role @membre @role`.")
 
 
@remove_group.command(name="role")
async def remove_role_cmd(ctx: commands.Context, membre: discord.Member, *, role: discord.Role):
    if not is_staff(ctx.author):
        await ctx.send("❌ Cette commande est réservée au staff.")
        return
 
    if role >= ctx.guild.me.top_role:
        await ctx.send("❌ Je ne peux pas retirer un rôle égal ou supérieur à mon rôle le plus haut.")
        return
 
    try:
        await membre.remove_roles(role, reason=f"Retiré par {ctx.author}")
    except discord.Forbidden:
        await ctx.send("❌ Permissions insuffisantes pour retirer ce rôle.")
        return
    except discord.HTTPException:
        await ctx.send("❌ Erreur lors du retrait du rôle.")
        return
 
    await ctx.send(f"✅ Le rôle {role.mention} a été retiré à {membre.mention}.")
 
 
# ================================================================
#                    SYSTÈME ANTI-SPAM
# ================================================================
#
# Si un membre envoie 3 fois de suite le même message (dans une fenêtre de
# 60 secondes), le bot l'avertit. Le compteur est en mémoire (pas persisté
# dans config.json), il se remet donc à zéro si le bot redémarre.

SPAM_WINDOW_SECONDS = 60
SPAM_THRESHOLD = 3

spam_tracker: dict[tuple[int, int], dict] = {}  # (guild_id, user_id) -> {"content", "count", "last_time"}


async def check_spam(message: discord.Message) -> None:
    contenu = message.content.strip().lower()
    if not contenu:
        return

    cle = (message.guild.id, message.author.id)
    maintenant = datetime.now(PARIS_TZ)
    entree = spam_tracker.get(cle)

    if entree and entree["content"] == contenu and (maintenant - entree["last_time"]).total_seconds() <= SPAM_WINDOW_SECONDS:
        entree["count"] += 1
        entree["last_time"] = maintenant
    else:
        entree = {"content": contenu, "count": 1, "last_time": maintenant}

    spam_tracker[cle] = entree

    if entree["count"] >= SPAM_THRESHOLD:
        entree["count"] = 0  # évite de ré-avertir à chaque nouveau message identique
        try:
            await message.channel.send(
                f"⚠️ {message.author.mention}, merci d'éviter d'envoyer plusieurs fois le même message (anti-spam)."
            )
        except discord.HTTPException:
            pass


# ================================================================
#                          on_message
# ================================================================
 
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
 
    if message.guild is not None:
        await check_spam(message)
        await check_flood(message)
        # Comptage pour l'Élu de la semaine
        bump_weekly_count(message.guild.id, message.author.id)
 
    if message.content.lower().strip() == "+concept list reset":
        if not is_staff(message.author):
            await message.channel.send("❌ Cette commande est réservée au staff.")
            return
 
        save_concept_list(message.guild.id, [])
        await message.channel.send("✅ La **liste Concept** a été entièrement réinitialisée.")
        return
 
    await bot.process_commands(message)
 
 
# ================================================================
#                    GESTION GLOBALE DES ERREURS
# ================================================================
#
# Évite que des erreurs comme "403 Forbidden : permissions manquantes"
# fassent planter une commande sans explication claire, et permet de
# prévenir la personne concernée plutôt que de simplement écrire dans les logs.
 
@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError):
    if isinstance(error, commands.CommandNotFound):
        return
 
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Argument manquant : `{error.param.name}`. Vérifie la syntaxe avec `+cmds`.")
        return
 
    if isinstance(error, (commands.BadArgument, commands.MemberNotFound, commands.RoleNotFound)):
        await ctx.send("❌ Argument invalide (membre, rôle ou valeur introuvable). Vérifie ta commande.")
        return
 
    original = getattr(error, "original", error)
 
    if isinstance(original, discord.Forbidden):
        salon_nom = ctx.channel.mention if hasattr(ctx.channel, "mention") else str(ctx.channel)
        avertissement = (
            f"❌ Je n'ai pas les permissions nécessaires pour exécuter `{ctx.command}` dans {salon_nom} "
            f"sur **{ctx.guild.name if ctx.guild else 'ce serveur'}**.\n"
            "Un membre du staff doit vérifier que mon rôle a bien les permissions "
            "**Envoyer des messages**, **Intégrer des liens** et **Gérer les salons/rôles** (selon la commande)."
        )
        try:
            await ctx.send(avertissement)
        except discord.Forbidden:
            # Impossible d'écrire même le message d'erreur dans ce salon : on prévient en DM.
            try:
                await ctx.author.send(avertissement)
            except discord.HTTPException:
                pass
        return
 
    print(f"⚠️ Erreur non gérée dans la commande '{ctx.command}': {error}")
 
 
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    original = getattr(error, "original", error)
 
    if isinstance(original, discord.Forbidden):
        message = (
            "❌ Je n'ai pas les permissions nécessaires pour exécuter cette action ici "
            "(vérifie mes permissions dans ce salon/cette catégorie)."
        )
    elif isinstance(error, app_commands.MissingPermissions):
        message = "❌ Tu n'as pas la permission d'utiliser cette commande."
    else:
        message = "❌ Une erreur est survenue lors de l'exécution de cette commande."
        print(f"⚠️ Erreur non gérée dans la commande slash '{interaction.command}': {error}")
 
    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except discord.HTTPException:
        pass
 
 
# ================================================================
#                          EVENTS
# ================================================================
 
@bot.event
async def on_ready():
    bot.add_view(AbsenceView())
    bot.add_view(TicketCloseView())

    # Reconstruit les panneaux de tickets existants pour que les boutons
    # restent fonctionnels après un redémarrage du bot.
    for guild_id_str, guild_conf in config.items():
        for panel_id, panel_data in guild_conf.get("ticket_panels", {}).items():
            try:
                bot.add_view(build_ticket_panel_view(panel_id, panel_data["buttons"]))
            except Exception as e:
                print(f"Erreur lors de la reconstruction du panneau de tickets {panel_id} : {e}")

    try:
        guild_obj = discord.Object(id=DEV_GUILD_ID)

        # 1) On copie les commandes (définies globalement dans le code) vers le
        #    serveur de dev, puis on les synchronise dessus (quasi instantané).
        bot.tree.copy_global_to(guild=guild_obj)
        synced = await bot.tree.sync(guild=guild_obj)
        print(f"{len(synced)} commande(s) slash synchronisée(s) sur le serveur de dev.")

        # 2) On vide ensuite la liste des commandes GLOBALES côté Discord.
        #    Sans cette étape, si une synchro globale a déjà eu lieu une fois
        #    (ex: `bot.tree.sync()` sans guild), Discord affiche chaque
        #    commande en double (une version globale + une version serveur).
        bot.tree.clear_commands(guild=None)
        await bot.tree.sync()
        print("Commandes globales nettoyées (évite les doublons dans /).")
    except Exception as e:
        print(f"Erreur de synchronisation : {e}")
 
    for guild in bot.guilds:
        await update_invites_cache(guild)
 
    if not update_stats_loop.is_running():
        update_stats_loop.start()
 
    if not check_elu_semaine.is_running():
        check_elu_semaine.start()
 
    if not check_anniversaires.is_running():
        check_anniversaires.start()

    if not check_tiktok_loop.is_running():
        check_tiktok_loop.start()

    if not check_animal_spawns.is_running():
        check_animal_spawns.start()

    print(f"✅ Connecté en tant que {bot.user}")
 
if __name__ == "__main__":
    TOKEN = os.getenv("DISCORD_TOKEN")
    if not TOKEN:
        raise RuntimeError("Défini la variable d'environnement DISCORD_TOKEN avant de lancer le bot.")
    bot.run(TOKEN)
