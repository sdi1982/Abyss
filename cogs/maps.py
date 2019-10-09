import asyncio
import random

from cogs.utils.formats import *
from cogs.utils.items import Unusable


def ensure_searched(func):
    async def check(ctx):
        c = int(await ctx.bot.redis.get(f'{ctx.author.id}:searchedmap-{ctx.player.map.name}'))
        if not c:
            raise NotSearched()
        return True

    return commands.check(check)(func)


class Maps(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_before_invoke(self, ctx):
        if ctx.author.id in self.bot.get_cog("BattleSystem").battles:
            raise SilentError  # cant use these commands during battle
        if ctx.command is self.inventory:
            return  # we dont want to interrupt the search if we are just opening our inventory
        if random.randint(1, 5) == 1:
            await ctx.invoke(self.bot.get_command("encounter"), force=True)
            raise SilentError

    @commands.command()
    @ensure_player
    async def whereami(self, ctx):
        """Tells you where you are currently located."""
        await ctx.send(f'You are currently on map "{ctx.player.map.name}", area "{ctx.player.area}".')

    @commands.command()
    @ensure_player
    async def search(self, ctx):
        """Looks around to see what you can interact with.
        Has a chance of spawning an enemy, interrupting the search."""
        await self.bot.redis.set(f'{ctx.author.id}:searchedmap-{ctx.player.map.name}:{ctx.player.area}', 1)
        tcount = ctx.player.map.areas[ctx.player.area]['treasurecount']
        locs = sum(1 for loc in ctx.player.map.areas[ctx.player.area]['interactions'] if loc['type'] == 0)
        chests = sum(1 for i in ctx.player.map.areas[ctx.player.area]['interactions'] if i['type'] == 1)
        await ctx.send(f'You looked around {ctx.player.map.name}#{ctx.player.area} and found {tcount} treasures, '
                       f'{locs} doors and {chests} chests.')

    @commands.command()
    @ensure_player
    async def inventory(self, ctx):
        """Opens your inventory and shows your items.
        You can select some items and use them if you wish,
        though some items may only be used in battle."""
        await ctx.player.inventory.view(ctx)
        c1 = self.bot.loop.create_task(
            self.bot.wait_for(
                "message",
                check=lambda m: m.author == ctx.author and m.channel == ctx.channel and ctx.player.inventory.has_item(
                    m.content.lower()),
                timeout=60))
        c2 = self.bot.loop.create_task(ctx.player.inventory.pg.wait_stop())
        await asyncio.wait([c1, c2], return_when=asyncio.FIRST_COMPLETED)
        await ctx.player.inventory.pg.stop()
        if c2.done():
            c1.cancel()
            return
        try:
            m = c1.result()
        except asyncio.TimeoutError:
            return

        item = ctx.player.inventory.get_item(m.content.lower())
        try:
            await item.use(ctx)
        except Unusable as e:
            await ctx.send(str(e))
            return
        if not ctx.player.inventory.remove_item(item):
            self.bot.log.warning(f"apparently {ctx.player} has {item}, but we couldnt remove it for some reason")

    @commands.command(enabled=False)
    @ensure_player
    @ensure_searched
    async def move(self, ctx):
        """Moves to another location.
        You can find what locations are available after `search`ing."""

    @commands.command(enabled=False)
    @ensure_player
    @ensure_searched
    async def interact(self, ctx):
        """Interacts with an object in this area.
        You can find what objects are available after `search`ing."""

    @commands.command(enabled=False)
    @ensure_player
    @ensure_searched
    async def open_treasure(self, ctx):
        """Opens a treasure in this room, if there are any remaining.
        Treasures reset daily at midnight UTC."""


def setup(bot):
    bot.add_cog(Maps(bot))
