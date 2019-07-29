import asyncio
import contextlib
import itertools
import random
from operator import itemgetter

import discord
from discord.ext import commands, ui

from .utils import lookups, scripts, i18n, imaging
from .utils.objects import Skill
from .utils.player import Player

import collections


FMT = {
    'weak': 'Weak to:',
    'resist': 'Resists:',
    'immune': 'Immune to:',
    'absorb': 'Absorbs:',
    'reflect': 'Reflects:'
}


class LRUDict(collections.OrderedDict):
    """a dictionary with fixed size, sorted by last use

    credit to lambda#0987"""

    def __init__(self, size, bot):
        super().__init__()
        self.size = size
        self.bot = bot

    def __getitem__(self, key):
        # move key to the end
        result = super().__getitem__(key)
        del self[key]
        super().__setitem__(key, result)
        return result

    def __setitem__(self, key, value):
        try:
            # if an entry exists at key, make sure it's moved up
            del self[key]
        except KeyError:
            # we only need to do this when adding a new key
            if len(self) >= self.size:
                k, v = self.popitem(last=False)
                asyncio.run_coroutine_threadsafe(v.save(self.bot), loop=self.bot.loop)

        super().__setitem__(key, value)


def prepare_skill_tree_page(player):
    embed = discord.Embed(colour=lookups.TYPE_TO_COLOUR[player.specialty.name.lower()])
    embed.title = _("Skill tree status")
    embed.set_author(name=player.name, icon_url=player.owner.avatar_url_as(format="png", size=32))
    leaf = player.leaf['cost']//1000 if player.leaf else 'N/A'
    embed.description = _("""Current leaf: {player._active_leaf}
AP Points: {player.ap_points} | {leaf} to finish.""").format(player=player, leaf=leaf)
    embed.set_footer(text=_("<~ Stats | Skills ~>"))
    return embed


def skills_page(player):
    embed = discord.Embed(colour=lookups.TYPE_TO_COLOUR[player.specialty.name.lower()])
    embed.title = _("Skills")
    embed.set_author(name=player.name, icon_url=player.owner.avatar_url_as(format='png', size=32))
    skills = [f'{lookups.TYPE_TO_EMOJI[skill.type.name.lower()]} {skill.name}' for skill in player.skills]
    embed.description = '\n'.join(skills) or ':warning:'
    embed.set_footer(text=_('<~ Skill Tree Status | Unset skills ~>'))
    return embed


def unset_skills_page(player):
    embed = discord.Embed(colour=lookups.TYPE_TO_COLOUR[player.specialty.name.lower()])
    embed.title = _("Unused skills")
    embed.set_author(name=player.name, icon_url=player.owner.avatar_url_as(format='png', size=32))
    skills = [f'{lookups.TYPE_TO_EMOJI[skill.type.name.lower()]} {skill.name}' for skill in player.unset_skills]
    embed.description = '\n'.join(skills) or _('(All skills equipped)')
    embed.set_footer(text=_('<~ Skills'))
    return embed


def stats_page(player):
    embed = discord.Embed(colour=lookups.TYPE_TO_COLOUR[player.specialty.name.lower()])
    embed.title = _("{}'s stats.").format(player.name)
    embed.set_author(name=player.name, icon_url=player.owner.avatar_url_as(format='png', size=32))
    embed.description = f"""\u2694 {_('Strength')}: {player.strength}
\u2728 {_('Magic')}: {player.magic}
\U0001f6e1 {_('Endurance')}: {player.endurance}
\U0001f3c3 {_('Agility')}: {player.agility}
\U0001f340 {_('Luck')}: {player.luck}"""
    embed.set_footer(text=_('<~ Home | Skill Tree Status ~>'))


class Status(ui.Session):
    def __init__(self, player):
        super().__init__(timeout=120)
        self.player = player
        embed = discord.Embed(title=player.name, colour=lookups.TYPE_TO_COLOUR[player.specialty.name.lower()])
        embed.set_author(name=player.owner, icon_url=player.owner.avatar_url_as(format="png", size=32))
        res = {}
        for key, value_iter in itertools.groupby(list(player.resistances.items()), key=itemgetter(1)):
            res.setdefault(key.name.lower(), []).extend([v[0].name.lower() for v in value_iter])
        res.pop("normal", None)
        spec = f"{lookups.TYPE_TO_EMOJI[player.specialty.name.lower()]} {player.specialty.name.title()}"
        res_fmt = "\n".join(
            [f"{FMT[k]}: {' '.join(map(lambda x: str(lookups.TYPE_TO_EMOJI[x.lower()]), v))}" for k, v in res.items()])
        arcana = lookups.ROMAN_NUMERAL[player.arcana.value]
        desc = _("""**{arcana}** {player.arcana.name}

{player.description}

Specializes in {spec} type skills.

__Resistances__
{res_fmt}""").format(**locals())
        embed.description = desc
        embed.set_footer(text=_('Stats ~>'))
        self.pages = [embed, stats_page(player), prepare_skill_tree_page(player),
                      skills_page(player), unset_skills_page(player)]
        self.current_page = 0

    async def send_initial_message(self):
        m = _('You can level up! Use `$levelup`!')
        return await self.context.send(m if self.player.can_level_up else None, embed=self.pages[0])

    async def handle_timeout(self):
        await self.stop()

    async def stop(self):
        with contextlib.suppress(discord.HTTPException):
            await self.message.delete()

    @ui.button('\u25c0')
    async def back(self, _):
        if self.current_page + 1 > 0:
            self.current_page -= 1
        else:
            return
        await self.message.edit(embed=self.pages[self.current_page])

    @ui.button('\u23f9')
    async def _stop(self, _):
        await self.stop()

    @ui.button('\u25b6')
    async def next(self, _):
        if self.current_page + 1 < len(self.pages):
            self.current_page += 1
        else:
            return
        await self.message.edit(embed=self.pages[self.current_page])


class Statistics(ui.Session):
    def __init__(self, player):
        super().__init__()
        self.player = player
        self.tots = [0, 0, 0, 0, 0]

    async def send_initial_message(self):
        self.message = await self.context.send(".")
        await self.update()
        return self.message

    async def update(self):
        embed = discord.Embed(title="Distribute your stat points!")
        embed.set_author(name=f'{self.player.name} levelled to L{self.player.level}')
        embed.description = f"""Points remaining: {self.player.stat_points}

\u2694 Strength: {self.player.strength}{f'+{self.tots[0]}' if self.tots[0] else ''}
\u2728 Magic: {self.player.magic}{f'+{self.tots[1]}' if self.tots[1] else ''}
\U0001f6e1 Endurance: {self.player.endurance}{f'+{self.tots[2]}' if self.tots[2] else ''}
\U0001f3c3 Agility: {self.player.agility}{f'+{self.tots[3]}' if self.tots[3] else ''}
\U0001f340 Luck: {self.player.luck}{f'+{self.tots[4]}' if self.tots[4] else ''}

\U0001f504 Reset distribution
\u2705 Confirm"""
        await self.message.edit(content="", embed=embed)

    @ui.button('\u2694')  # strength
    async def add_strength(self, _):
        if self.player.stat_points == 0:
            return
        self.tots[0] += 1
        self.player.stat_points -= 1
        await self.update()

    @ui.button('\u2728')  # magic
    async def add_magic(self, _):
        if self.player.stat_points == 0:
            return
        self.tots[1] += 1
        self.player.stat_points -= 1
        await self.update()

    @ui.button('\U0001f6e1')  # endurance
    async def add_endurance(self, _):
        if self.player.stat_points == 0:
            return
        self.tots[2] += 1
        self.player.stat_points -= 1
        await self.update()

    @ui.button('\U0001f3c3')  # agility
    async def add_agility(self, _):
        if self.player.stat_points == 0:
            return
        self.tots[3] += 1
        self.player.stat_points -= 1
        await self.update()

    @ui.button('\U0001f340')  # luck
    async def add_luck(self, _):
        if self.player.stat_points == 0:
            return
        self.tots[4] += 1
        self.player.stat_points -= 1
        await self.update()

    @ui.button('\U0001f504')  # reset
    async def reset(self, _):
        self.player.stat_points = sum(self.tots) + self.player.stat_points
        self.tots = [0, 0, 0, 0, 0]
        await self.update()

    @ui.button('\u2705')  # confirm
    async def confirm(self, _):
        self.player.strength += self.tots[0]
        self.player.magic += self.tots[1]
        self.player.endurance += self.tots[2]
        self.player.agility += self.tots[3]
        self.player.luck += self.tots[4]
        await self.message.delete()

    async def stop(self):
        with contextlib.suppress(discord.HTTPException):
            await super().stop()


class Players(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.players = LRUDict(20, bot)
        self.skill_cache = {}
        self._base_demon_cache = {}
        self._skill_cache_task = self.bot.loop.create_task(self.cache_skills())
        self.bot.unload_tasks[self] = self._unloader_task = self.bot.loop.create_task(self.flush_cached_players())

    def __repr__(self):
        return f"<PlayerHandler {len(self.players)} loaded,\n\t{self._skill_cache_task!r}>"

    def cog_unload(self):
        task = self.bot.unload_tasks.pop(self)
        task.cancel()

    async def flush_cached_players(self):
        await self.bot.wait_for("logout")
        for i in range(len(self.players)):
            _, player = self.players.popitem()
            await player.save(self.bot)

    async def cache_skills(self):
        await self.bot.prepared.wait()

        async for skill in self.bot.db.abyss.skills.find():
            skill.pop("_id")
            self.skill_cache[skill['name']] = Skill(**skill)

        self.bot.tree.do_cuz_ready()

        async for demon in self.bot.db.abyss.basedemons.find():
            demon.pop("_id")
            self._base_demon_cache[demon['name']] = demon

    # -- finally, some fucking commands -- #

    @commands.command()
    @commands.cooldown(1, 86400, commands.BucketType.user)
    async def create(self, ctx):
        """Creates a new player.
        You will be given a random demon to use throughout your journey."""
        if ctx.player:
            return await ctx.send(_("You already own a player."))

        msg = _("This appears to be a public server. The messages sent can get spammy, or cause ratelimits.\n"
                "It is advised to use a private server/channel.")

        if sum(not m.bot for m in ctx.channel.members) > 100:
            await ctx.send(msg)
            await asyncio.sleep(5)

        task = self.bot.loop.create_task(scripts.do_script(ctx, "creation", i18n.current_locale.get()))

        if not await self.bot.is_owner(ctx.author):
            demon = random.choice(list(self._base_demon_cache.keys()))
            data = self._base_demon_cache[demon]
            while data.get('testing', False):
                demon = random.choice(list(self._base_demon_cache.keys()))
                data = self._base_demon_cache[demon]
        else:
            data = self._base_demon_cache['debug']
            data['testing'] = True
        data['owner'] = ctx.author.id
        data['exp'] = 0
        data['skill_leaf'] = None
        data['unsetskills'] = []
        player = Player(**data)

        await task
        if not task.result():
            ctx.command.reset_cooldown(ctx)
            return

        await self.bot.redis.set(f"story@{ctx.author.id}", 1)

        self.players[ctx.author.id] = player
        player._populate_skills(self.bot)
        await player.save(self.bot)

        await ctx.send(
            _("<꽦䐯嬜継ḉ> The deed is done. You have been given the demon `{player.name}`. Use its power wisely..."
              ).format(player=player))

    @commands.command()
    async def status(self, ctx):
        """Gets your current players status."""
        if not ctx.player:
            return await ctx.send(_("You don't own a player."))
        
        session = Status(ctx.player)
        await session.start(ctx)

    @commands.command()
    async def delete(self, ctx):
        """Deletes your player.
        ! THIS ACTION IS IRREVERSIBLE !"""
        if not ctx.player:
            return

        m1 = await ctx.send(_("Are you sure you want to delete your account? This action is irreversible."))
        if not await self.bot.confirm(m1, ctx.author):
            return

        m2 = await ctx.send(_("...are you really sure?"))
        if not await self.bot.confirm(m2, ctx.author):
            return

        await asyncio.gather(m1.delete(), m2.delete())

        self.players.pop(ctx.author.id)
        await self.bot.db.abyss.accounts.delete_one({"owner": ctx.author.id})
        await ctx.send(self.bot.tick_yes)

    @commands.command(hidden=True)
    async def profile(self, ctx):
        if not ctx.player:
            return await ctx.send(_("You don't own a player."))

        data = await imaging.profile_executor(self.bot, ctx.player)
        await ctx.send(file=discord.File(data, 'profile.png'))

    @commands.command()
    async def levelup(self, ctx):
        """Levels up your player, if possible.
        Also lets you divide your spare stat points to increase your stats."""
        if not ctx.player:
            return await ctx.send(_("You don't own a player."))
        if ctx.player.can_level_up:
            ctx.player.level_up()
        if ctx.player.stat_points > 0:
            new = Statistics(ctx.player)
            await new.start(ctx)
        else:
            await ctx.send(_("You have no skill points remaining."))

    @commands.command(name='set')
    async def _set(self, ctx, *, name):
        """Puts an inactive skill into your repertoire."""
        if not ctx.player:
            return
        name = name.title()
        if name not in self.skill_cache:
            return await ctx.send(_("Couldn't find a skill by that name."))
        skill = self.skill_cache[name]
        if skill not in ctx.player.unset_skills:
            if skill in ctx.player.skills:
                return await ctx.send(_("That skill is already in your repertoire."))
            return await ctx.send(_("You haven't unlocked that skill yet."))
        if len(ctx.player.skills) == 8:
            return await ctx.send(_("You can't equip more than 8 skills."))
        ctx.player.skills.append(skill)
        ctx.player.unset_skills.remove(skill)
        await ctx.send(self.bot.tick_yes)

    @commands.command()
    async def unset(self, ctx, *, name):
        """Removes an active skill from your repertoire."""
        if not ctx.player:
            return
        name = name.title()
        if name not in self.skill_cache:
            return await ctx.send(_("Couldn't find a skill by that name."))
        skill = self.skill_cache[name]
        if skill not in ctx.player.skills:
            if skill in ctx.player.unset_skills:
                return await ctx.send(_("That skill is not in your repertoire."))
            return await ctx.send(_("You haven't unlocked that skill yet."))
        if len(ctx.player.skills) == 1:
            return await ctx.send(_("You must equip at least 1 skill."))
        ctx.player.unset_skills.append(skill)
        ctx.player.skills.remove(skill)
        await ctx.send(self.bot.tick_yes)


def setup(bot):
    bot.add_cog(Players(bot))
