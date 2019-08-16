import asyncio
import contextlib
import io
import os
import numpy.random as random
import traceback
from datetime import datetime

import aiohttp
import aioredis
import discord
from discord.ext import commands
import motor.motor_asyncio

import config
from cogs.utils import i18n, formats
from cogs.utils.player import Player

import logging

NL = '\n'


class BetterRotatingFileHandler(logging.FileHandler):
    def __init__(self, *args, **kwargs):
        self.init = datetime.utcnow().strftime("%d-%m-%Y")
        super().__init__(*args, **kwargs)

    def _open(self):
        return open(self.baseFilename+self.init, 'a', encoding='utf-8')

    def emit(self, record):
        strf = datetime.utcnow().strftime("%d-%m-%Y")
        if strf != self.init:
            self.init = strf
            self.close()

        if self.stream is None:
            self.stream = self._open()

        return logging.StreamHandler.emit(self, record)


logger = logging.getLogger('discord')
logger.setLevel(logging.DEBUG)
handler = BetterRotatingFileHandler('logs/discord.log', encoding='utf-8')
handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
logger.addHandler(handler)


def do_next_script(msg, author=None):
    author = author or msg.author

    def check(r, u):
        return u.id == author.id and \
            r.message.id == msg.id and \
            str(r.emoji) == '\u25b6'
    return check


def get_logger():
    import builtins
    log = logging.getLogger(__name__)
    log.setLevel(logging.DEBUG)
    "uncomment the above line to enable debug logging"

    stream = logging.StreamHandler()

    stream.setFormatter(logging.Formatter("[{asctime} {name}/{levelname}]: {message}", "%H:%M:%S", "{"))

    log.handlers = [
        stream,
        BetterRotatingFileHandler("logs/log", encoding="utf-8")
    ]

    builtins.log = log
    return log


get_logger()


CONFIG_NEW = {
    "guild": None,              # guild id
    "prefixes": config.PREFIX,  # list of prefixes
    "autoMessages": True,       # toggle automatic messages in the entire guild
    "ignoreChannels": [],       # prevent automatic messages in these channels
    "blacklist": []             # ignore commands from these users
}


class ContextSoWeDontGetBannedBy403(commands.Context):
    async def send(self, content=None, *, embed=None, file=None, files=None, tts=False, **kwargs):
        if not self.guild.me.permissions_in(self.channel).send_messages:
            return
        if embed and not self.guild.me.permissions_in(self.channel).embed_links:
            return
        elif (file or files) and not self.guild.me.permissions_in(self.channel).attach_files:
            return
        elif tts and not self.guild.me.permissions_in(self.channel).send_tts_messages:
            return
        return await super().send(content, embed=embed, file=file, files=files, tts=tts, **kwargs)


class Abyss(commands.Bot):
    def __init__(self):
        super().__init__(commands.when_mentioned_or("$"))
        self.prepared = asyncio.Event()
        # `prepared` is to make sure the bot has loaded the database and such

        self.db = motor.motor_asyncio.AsyncIOMotorClient(
            username=config.MONGODB_USER, password=config.MONGODB_PASS, authSource=config.MONGODB_DBSE)
        self.redis = None
        self.session = aiohttp.ClientSession()

        self.tick_yes = config.TICK_YES
        self.tick_no = config.TICK_NO
        self.debug_hook = config.DEBUG_WEBHOOK
        self.unload_tasks = {}
        self.config = config
        self._ctx_locks = {}
        self.start_date = None

        self.help_command = commands.MinimalHelpCommand(verify_checks=False)

        self.add_check(self.global_check)
        self.before_invoke(self.before_invoke_handler)
        self.prepare_extensions()

    async def on_command_error(self, *__, **_):
        pass

    @property
    def description(self):
        return random.choice([
            "> ~~Stuck? Try using `$story` to progress.~~",
            "> Confused? Try `$faq` for more information.",
            "> ~~Bored? Try your hand at an online battle.~~",
            "> If you have spare stat points, you can still use `$levelup` to use them.",
            "> Join the support server for updates and announcements: <https://discord.gg/hkweDCD>",
            "> During scripts, press the stop button to save your progress. Using `$story` will continue where you left off.",
            "corn"
        ])

    @description.setter
    def description(self, value):
        pass

    @property
    def players(self):
        return self.get_cog("Players")

    @property
    def tree(self):
        return self.get_cog("SkillTreeCog")

    @property
    def maps(self):
        return self.get_cog("Maps")

    async def before_invoke_handler(self, ctx):
        if not self.players:
            ctx.player = None
            return
        try:
            ctx.player = self.players.players[ctx.author.id]
        except KeyError:
            data = await self.db.abyss.accounts.find_one({"owner": ctx.author.id})
            if not data:
                ctx.player = None
                return
            ctx.player = self.players.players[ctx.author.id] = player = Player(**data)
            player._populate_skills(self)
            if player._active_leaf is not None:
                key, _ = player._active_leaf.split(':')
                branch = self.tree.skill_tree[key].copy()
                branch[player._active_leaf]['name'] = player._active_leaf
                player.leaf = branch[player._active_leaf]

    async def wait_for_close(self):
        for cog, task in self.unload_tasks.items():
            try:
                await asyncio.wait_for(task, timeout=30)
            except asyncio.TimeoutError:
                log.warning(f"{cog!r} unload task did not finish in time.")
                task.cancel()

    # noinspection PyMethodMayBeStatic
    async def global_check(self, ctx):
        if not ctx.guild:
            raise commands.NoPrivateMessage
        return True

    # noinspection PyShadowingNames
    async def confirm(self, msg, user):
        rs = (str(self.tick_yes), str(self.tick_no))
        for r in rs:
            await msg.add_reaction(r)
        try:
            r, u = await self.wait_for('reaction_add', check=lambda r, u: str(r.emoji) in rs and u.id == user.id and
                                       r.message.id == msg.id, timeout=60)
        except asyncio.TimeoutError:
            return False
        else:
            if str(r.emoji) == rs[0]:
                return True
            return False
        finally:
            with contextlib.suppress(discord.Forbidden):
                await msg.clear_reactions()

    # noinspection PyTypeChecker
    async def _send_error(self, message):

        # Hey, if you've stumbled upon this, you might be asking:
        # "Xua, why are you instantiating your own DMChannel?"
        # My answer: no idea
        # I could save the stupidness and just use get_user.dm_channel
        # But what if an error happens pre on_ready?
        # The user might not be cached.

        # Of course, this wouldn't technically matter if the webhook exists,
        # but webhooks are optional so :rooShrug:

        if isinstance(config.DEBUG_WEBHOOK, str):
            if config.DEBUG_WEBHOOK:
                self.debug_hook = discord.Webhook.from_url(config.DEBUG_WEBHOOK,
                                                           adapter=discord.AsyncWebhookAdapter(self.session))
            else:
                data = await self.http.start_private_message(config.OWNERS[0])
                self.debug_hook = discord.DMChannel(me=self.user, state=self._connection, data=data)

        if isinstance(message, str) and len(message) > 2000:
            async with self.session.post("https://mystb.in/documents", data=message.encode()) as post:
                if post.status == 200:
                    data = await post.json()
                    return await self._send_error(f"Error too long: https://mystb.in/{data['key']}")

                # no mystbin, fallback to files
                f = io.BytesIO(message.encode())
                return await self._send_error(discord.File(f, "error.txt"))
        elif isinstance(message, discord.File):
            await self.debug_hook.send(file=message)
        else:
            await self.debug_hook.send(message)

    def send_error(self, message):
        return self.loop.create_task(self._send_error(message))

    def prepare_extensions(self):
        try:
            self.load_extension("jishaku")
        except commands.ExtensionNotFound:
            pass

        for file in os.listdir("cogs"):
            if file.endswith(".py"):
                file = file[:-3]

            if file in config.COG_BLACKLIST:
                continue

            filename = "cogs." + file

            try:
                self.load_extension(filename)
            except Exception as e:
                log.warning(f"Could not load ext `{filename}`.")
                self.send_error(f"Could not load ext `{filename}`\n```py\n{formats.format_exc(e)}\n````")

    async def on_ready(self):
        if self.prepared.is_set():
            await self.change_presence(activity=discord.Game(name="$help"))
            return

        try:
            await self.db.abyss.accounts.find_one({})
            # dummy query to ensure the db is connected
        except Exception as e:
            log.error("COULD NOT CONNECT TO MONGODB DATABASE.")
            log.error("This could lead to fatal errors. Falling back prefixes to mentions only.")
            self.send_error(f"FAILED TO CONNECT TO MONGODB\n```py\n{formats.format_exc(e)}\n```")
            return

        try:
            self.redis = await aioredis.create_redis_pool(**config.REDIS)
        except Exception as e:
            log.error("couldnt connect to redis")
            self.send_error(F"failed to connect to redis\n```py\n{formats.format_exc(e)}\n```")

        self.prepared.set()
        self.start_date = datetime.utcnow()
        log.warning("Successfully loaded.")
        await self.change_presence(activity=discord.Game(name="$help"))

    async def on_message(self, message):
        if message.author.bot:
            return

        current = await self.redis.get(f"locale:{message.author.id}")
        if not current:
            current = i18n.LOCALE_DEFAULT.encode()
        i18n.current_locale.set(current.decode())

        await self.process_commands(message)

    async def get_context(self, message, *, cls=None):
        return await super().get_context(message, cls=cls or ContextSoWeDontGetBannedBy403)

    async def on_message_edit(self, before, after):
        if after.author.bot or before.content == after.content:
            return

        current = await self.redis.get(f"locale:{before.author.id}")
        if not current:
            current = i18n.LOCALE_DEFAULT.encode()
        i18n.current_locale.set(current.decode())
        await self.process_commands(after)

    def run(self):
        # stupid sphinx inheriting bug
        super().run(config.TOKEN)

    async def close(self):
        self.dispatch("logout")
        await self.wait_for_close()
        self.db.close()
        await self.session.close()
        await super().close()

    async def on_error(self, event, *args, **kwargs):
        if not self.prepared.is_set():
            return
        to = f""">>> Error occured in event `{event}`
Arguments: {NL.join(map(repr, args))}
KW Arguments: {kwargs}
```py
{traceback.format_exc()}
```"""
        await self.send_error(to)
