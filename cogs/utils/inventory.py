import discord

from cogs.utils.items import dataclass
from .enums import ItemType
from .lookups import ITEM_TYPE_STRINGIFY
from .paginators import EmbedPaginator, PaginationHandler


@dataclass
class _ItemCount:
    def __init__(self, item, count=0):
        self.item = item
        self.count = count

    @property
    def name(self):
        return self.item.name

    def __eq__(self, other):
        return self.item == other

    def __bool__(self):
        return self.count > 0


class Inventory:
    def __init__(self, bot, player, data):
        self.player = player
        self.items = {}
        self.pg = None
        for tab, iids in data.items():
            self.items[tab] = []
            for item, count in iids:
                self.items[ItemType[tab]].append(_ItemCount(bot.item_cache.get_item(item), count))

    def __repr__(self):
        return f"<{self.player.owner.name}'s inventory, {sum(map(len, self.items.values()))} items>"

    def to_json(self):
        return {t.name: list(map(str, k)) for t, k in self.items.items()}

    async def view(self, ctx):
        pg = EmbedPaginator()
        for tab in self.items:
            pg.add_page(discord.Embed(title=f"<| {ITEM_TYPE_STRINGIFY[tab]} |>",
                                      description="\n".join(map(str, self.items[tab]))))
        self.pg = PaginationHandler(ctx.bot, pg, send_as='embed')
        await self.pg.start(ctx)

    def get_item(self, name):
        for t in self.items.values():
            for i in t:
                if i.name.lower() == name:
                    return i

    def has_item(self, name):
        """Case-insensitive search to check if a player has this item."""
        return self.get_item(name) is not None

    def add_item(self, item):
        if item.type not in self.items:
            self.items[item.type] = []
        if item not in self.items[item.type]:
            self.items[item.type].append(_ItemCount(item, 1))
        else:
            for i in self.items[item.type]:
                if i == item:
                    i.count += 1
                    break

    def remove_item(self, item):
        for tab, items in self.items.values():
            for i in items:
                if i == item:
                    i.count -= 1
                    if i.count <= 0:
                        self.items[tab].remove(i)
                    return True  # successful
        return False  # didnt remove anything, for debug purposes
