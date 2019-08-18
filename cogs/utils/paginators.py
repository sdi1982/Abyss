import asyncio

import discord


class BetterPaginator:
    def __init__(self, prefix=None, suffix=None, max_size=1985):
        self.prefix = prefix or ''
        self.suffix = suffix or ''
        self.max_size = max_size
        self._pages = []
        self._current_page = ""

    @property
    def pages(self):
        return self._pages + [f'{self.prefix}\n{self._current_page}\n{self.suffix}']

    def add_line(self, line='', empty=False):
        line += '\n'
        if empty:
            line += '\n'
        if len(self.prefix) + len(self._current_page) + len(self.suffix) + len(line) >= self.max_size:
            self._pages.append(f'{self.prefix}\n{self._current_page}\n{self.suffix}')
            self._current_page = ''
        self._current_page += line


class EmbedPaginator(BetterPaginator):
    def __init__(self):
        super().__init__(prefix="", suffix="", max_size=1985)

    def add_page(self, embed):
        self.pages.append(embed)


class PaginationHandler:
    def __init__(self, abyss, paginator: BetterPaginator, *,
                 owner=None, send_as="content", no_help=False):
        if paginator.max_size > 1985:
            raise TypeError(f"paginator is too big: {paginator.max_size}/1985")
        self.pg = paginator
        self.abyss = abyss
        self.current_page = 0
        self.msg = None
        bt = [None, None, '\N{RAISED HAND}', None, None]
        ex = [self.first_page, self.previous_page, self.stop, self.next_page, self.last_page]
        if not no_help:
            bt.append('\N{BLACK QUESTION MARK ORNAMENT}')
            ex.append(self.help)
        if len(self.pg.pages) > 1:
            bt[1] = '\U0001f448'
            bt[3] = '\U0001f449'
        if len(self.pg.pages) > 2:
            bt[0] = '\U0001f91b'
            bt[4] = '\U0001f91c'
        self.buttons = {
            k: ex[bt.index(k)] for k in bt if k
        }
        self.send_as = send_as
        self.has_perms = False
        self.owner = owner
        self._stop_event = asyncio.Event()
        self._timeout = abyss.loop.create_task(self._timeout_task())

    @property
    def send_kwargs(self):
        if len(self.pg.pages) > 1:
            if isinstance(self.page, discord.Embed):
                page = self.page.copy()
                if not self.page.footer:
                    page.set_footer(text=f"Page {self.current_page+1}/{len(self.pg.pages)}")
                else:
                    page.set_footer(text=f"{self.page.footer.text} | Page {self.current_page+1}/{len(self.pg.pages)}")
            else:
                page = self.page + f'\nPage {self.current_page+1}/{len(self.pg.pages)}'
        else:
            page = self.page
        return {self.send_as: page, ('embed' if self.send_as == 'content' else 'content'): None}

    @property
    def page(self):
        return self.pg.pages[self.current_page]

    async def _timeout_task(self):
        while True:
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=180)
            except asyncio.TimeoutError:
                await self.stop()
                break
            finally:
                self._stop_event.clear()

    async def _update(self):
        if len(self.pg.pages) > 1:
            self.buttons['\U0001f448'] = self.previous_page
            self.buttons['\U0001f449'] = self.next_page
        if len(self.pg.pages) > 2:
            self.buttons['\U0001f91b'] = self.first_page
            self.buttons['\U0001f91c'] = self.last_page
        for k in self.buttons:
            await self.msg.add_reaction(k)
        await self.msg.edit(**self.send_kwargs)

    async def _raw_reaction_event(self, payload):
        if not self.msg:
            return
        if payload.user_id != self.owner.id:
            return
        if payload.message_id != self.msg.id:
            return
        if self.has_perms and payload.event_type == 'REACTION_REMOVE':
            return
        if str(payload.emoji) not in self.buttons:
            return
        button = self.buttons[str(payload.emoji)]
        await button()
        if self.has_perms:
            await self.msg.remove_reaction(str(payload.emoji), self.owner)

    async def stop(self):
        """Stops the pagination."""
        self._timeout.cancel()
        if self.has_perms:
            await self.msg.clear_reactions()
        else:
            await self.msg.delete()

    async def start(self, ctx):
        self.msg = await ctx.send(**self.send_kwargs)
        if not self.owner:
            self.owner = ctx.author
        for r in self.buttons:
            await self.msg.add_reaction(r)
        self.abyss.add_listener(self._raw_reaction_event, "on_raw_reaction_add")
        if not ctx.channel.permissions_for(ctx.me).manage_messages:
            self.abyss.add_listener(self._raw_reaction_event, "on_raw_reaction_remove")
        else:
            self.has_perms = True

    async def help(self):
        """Shows this screen."""
        e = discord.Embed(title="Paginator Help")
        e.description = '\n'.join(f'{m} {f.__doc__}' for m, f in self.buttons.items())
        e.description += "\n\nIf I don't have `Manage Messages` permissions, removing reactions will also trigger" \
                         " the buttons."
        e.set_footer(text="Session will timeout after 180s")
        await self.msg.edit(content=None, embed=e)

    async def first_page(self):
        """Brings you back to the first page."""
        if not self.msg:
            raise RuntimeError

        self.current_page = 0
        await self.msg.edit(**self.send_kwargs)

    async def last_page(self):
        """Brings you to the last page."""
        if not self.msg:
            raise RuntimeError

        self.current_page = len(self.pg.pages)-1
        await self.msg.edit(**self.send_kwargs)

    async def previous_page(self):
        """Goes back 1 page."""
        if not self.msg:
            raise RuntimeError("initial message not sent")

        if self.current_page == 0:
            return
        self.current_page -= 1
        await self.msg.edit(**self.send_kwargs)

    async def next_page(self):
        """Goes forward one page."""
        if not self.msg:
            raise RuntimeError("initial message not sent")

        if self.current_page == len(self.pg.pages)-1:
            return
        self.current_page += 1
        await self.msg.edit(**self.send_kwargs)
