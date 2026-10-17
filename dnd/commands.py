import asyncio
import io
import logging
import discord
from discord import app_commands
from dnd.abilities import AbilityError

class AbilitySelect(discord.ui.Select):
    def __init__(self, options):
        super().__init__(placeholder='Choose an ability', options=options)

    async def callback(self, interaction):
        await self.view.show_ability(interaction, self.values[0])

class AbilityView(discord.ui.View):
    def __init__(self, service, catalog, character_id, user_id):
        super().__init__(timeout=300)
        self.service, self.catalog = service, catalog
        self.character_id, self.user_id = character_id, user_id
        self.page = 0
        self.rebuild()

    def entries(self):
        return sorted(self.catalog.assignments[self.character_id],
                      key=lambda assignment: self.catalog.abilities[assignment.ability_id].name.casefold())

    def rebuild(self):
        for child in list(self.children):
            if isinstance(child, AbilitySelect):
                self.remove_item(child)
        entries = self.entries()
        self.page = min(self.page, max(0, (len(entries) - 1) // 25))
        visible = entries[self.page * 25:(self.page + 1) * 25]
        if visible:
            self.add_item(AbilitySelect([discord.SelectOption(
                label=self.catalog.abilities[entry.ability_id].name, value=entry.ability_id) for entry in visible]))
        self.previous.disabled = self.page == 0
        self.next_page.disabled = (self.page + 1) * 25 >= len(entries)

    def embed(self, ability_id=None):
        character = self.catalog.characters[self.character_id]
        entries = self.entries()
        if ability_id:
            assignment = next((entry for entry in entries if entry.ability_id == ability_id), None)
            if assignment is None:
                raise AbilityError('That ability is not assigned to this character.')
            ability = self.catalog.abilities[ability_id]
            description = ability.description
            if assignment.notes:
                description += '\n\nCharacter notes:\n' + assignment.notes
            attachments = []
            if len(description) > 4096:
                attachments = [discord.File(io.BytesIO(description.encode('utf-8')), filename='ability-description.txt')]
                description = description[:3900] + '\n\nFull description attached as a text file.'
            embed = discord.Embed(title=ability.name, description=description, url=self.service.source_url)
            if ability.type:
                embed.add_field(name='Type', value=ability.type[:1024], inline=False)
        else:
            description = 'Choose an ability from the dropdown.' if entries else 'No abilities are assigned to this character yet.'
            embed = discord.Embed(title=f'{character.name} — Abilities', description=description, url=self.service.source_url)
            attachments = []
        embed.set_footer(text=f'{character.name} | {len(entries)} abilities | Page {self.page + 1}/{max(1, (len(entries) + 24) // 25)}')
        return embed, attachments

    async def interaction_check(self, interaction):
        if interaction.user.id == self.user_id:
            return True
        await interaction.response.send_message('Run /abilities to open your own ability menu.', ephemeral=True)
        return False

    async def show_ability(self, interaction, ability_id=None):
        embed, attachments = self.embed(ability_id)
        try:
            await interaction.response.edit_message(embed=embed, view=self, attachments=attachments)
        finally:
            for attachment in attachments:
                attachment.close()

    @discord.ui.button(label='Previous', row=1)
    async def previous(self, interaction, button):
        self.page = max(0, self.page - 1)
        self.rebuild()
        await self.show_ability(interaction)

    @discord.ui.button(label='Next', row=1)
    async def next_page(self, interaction, button):
        self.page = min(max(0, (len(self.entries()) - 1) // 25), self.page + 1)
        self.rebuild()
        await self.show_ability(interaction)

    @discord.ui.button(label='Refresh', row=1)
    async def refresh(self, interaction, button):
        await interaction.response.defer()
        catalog = await self.service.load(force=True)
        if self.character_id not in catalog.characters:
            raise AbilityError('This character was removed from the Sheet. Run /abilities again.')
        self.catalog = catalog
        self.rebuild()
        embed, attachments = self.embed()
        await interaction.edit_original_response(embed=embed, view=self, attachments=[])

    async def on_error(self, interaction, error, item):
        if isinstance(error, ValueError):
            message = str(error)
        else:
            logging.error('Ability menu failed', exc_info=(type(error), error, error.__traceback__))
            message = 'Ability lookup failed. Try /abilities again.'
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

def register_ability_commands(bot, service):
    @bot.tree.command(name='abilities', description='Browse a character’s homebrew abilities')
    @app_commands.guild_only()
    @app_commands.describe(character='Choose your character')
    async def abilities(interaction: discord.Interaction, character: str):
        await interaction.response.defer(ephemeral=True)
        catalog = await service.load()
        selected = catalog.character(character)
        view = AbilityView(service, catalog, selected.id, interaction.user.id)
        embed, _ = view.embed()
        await interaction.followup.send(embed=embed, view=view, ephemeral=True,
                                        allowed_mentions=discord.AllowedMentions.none())

    @abilities.autocomplete('character')
    async def character_autocomplete(interaction, current):
        catalog = service.cached
        if catalog is None:
            try:
                catalog = await asyncio.wait_for(service.load(), timeout=2)
            except (ValueError, asyncio.TimeoutError):
                return []
        names = sorted((character.name for character in catalog.characters.values()), key=str.casefold)
        return [app_commands.Choice(name=name, value=name) for name in names if current.casefold() in name.casefold()][:25]
