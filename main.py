import os
import json
import asyncio
import aiohttp
import discord
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv
load_dotenv()

# ================================================================
#                        CONFIGURATION
# ================================================================
PREFIX = "+"

STAFF_ROLE_NAME = "Staff"               # Nom exact du rôle staff sur ton serveur
STATS_CATEGORY_NAME = "🧽 SERVEUR STATS"
STATS_UPDATE_INTERVAL_MINUTES = 10      # Discord limite les renommages de salons (~2 / 10 min)
CONFIG_FILE = "config.json"             # Stockage persistant des rôles autorisés à valider
DEV_GUILD_ID = 1539254757951021147      # ID de ton serveur, pour une synchro instantanée des slash commands
 
# ---- Élu de la semaine ----
ELU_ROLE_NAME = "👑 Élu de la semaine"
ELU_GIF_URL = "https://media1.tenor.com/m/9BEFbzse_iUAAAAC/hunter-x-hunter-vacuum.gif"
PARIS_TZ = ZoneInfo("Europe/Paris")
# ================================================================
 
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
 
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
]
 
STAFF_COMMANDS = [
    ("+absences", "Ouvre un formulaire pour déclarer une absence."),
    ("+role-react setup", "Crée un message à réactions qui donne des rôles."),
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
]
 
 
@bot.command(name="cmds")
async def cmds_command(ctx: commands.Context, sous_commande: str = None):
    if sous_commande and sous_commande.lower() == "staff":
        if not is_staff(ctx.author):
            await ctx.send("❌ Tu n'as pas la permission de voir les commandes staff.")
            return
        embed = discord.Embed(title="🛠️ Commandes Staff", color=discord.Color.red())
        for name, desc in STAFF_COMMANDS:
            embed.add_field(name=name, value=desc, inline=False)
        await ctx.send(embed=embed)
        return
 
    embed = discord.Embed(title="📜 Liste des commandes", color=discord.Color.blurple())
    for name, desc in NORMAL_COMMANDS:
        embed.add_field(name=name, value=desc, inline=False)
    embed.set_footer(text="Tape +cmds staff si tu es membre du staff pour voir plus de commandes.")
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
#                          on_message
# ================================================================
 
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
 
    # Comptage pour l'Élu de la semaine
    if message.guild is not None:
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
#                          EVENTS
# ================================================================
 
@bot.event
async def on_ready():
    bot.add_view(AbsenceView())
    try:
        guild_obj = discord.Object(id=DEV_GUILD_ID)
        bot.tree.copy_global_to(guild=guild_obj)
        synced = await bot.tree.sync(guild=guild_obj)
        print(f"{len(synced)} commande(s) slash synchronisée(s) sur le serveur de dev.")
    except Exception as e:
        print(f"Erreur de synchronisation : {e}")
 
    for guild in bot.guilds:
        await update_invites_cache(guild)
 
    if not update_stats_loop.is_running():
        update_stats_loop.start()
 
    if not check_elu_semaine.is_running():
        check_elu_semaine.start()
 
    print(f"✅ Connecté en tant que {bot.user}")
 
 
if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("Défini la variable d'environnement DISCORD_TOKEN avant de lancer le bot.")
     TOKEN = os.getenv("DISCORD_TOKEN")
    bot.run(TOKEN)
 
