import numpy.random as random


class UserIsImmobilized(Exception):
    pass  # raise this when you are unable to move


class UserTurnInterrupted(Exception):
    pass  # raise this when your turn was interrupted (eg confuse/brainwash)


class AilmentRemoved(Exception):
    pass  # raise this when the ailment has been removed


class _Ailment:
    emote = None
    # the emote to appear next to the user inflicted with this ailment

    def __init__(self, player, type):
        self.type = type
        self.player = player
        self.counter = 0
        self.clear_at = random.randint(2, 7)

    def __repr__(self):
        return f"<Ailment: {self.name}, {self.player!r}, {self.counter}, {self.type!r}>"

    @property
    def name(self):
        return self.__class__.__name__

    # Forget is already handled in battle

    def pre_turn_effect(self):
        # for freeze, shock, sleep, confuse, fear, despair, rage, brainwash
        if self.counter == self.clear_at:
            raise AilmentRemoved
        self.counter += 1

    def post_turn_effect(self):
        pass  # for burn


class Burn(_Ailment):
    """
    After you take your turn, you will take 6% of your max HP in damage.
    """
    emote = "\N{FIRE}"

    def post_turn_effect(self):
        self.player.hp = self.player.max_hp * 0.06


class Forget(_Ailment):
    """
    You will be unable to use your skills.
    You can still use Attack and Guard, and your passive skills will still work.
    """
    emote = '\N{SPEAKER WITH CANCELLATION STROKE}'


class Freeze(_Ailment):
    """
    You are unable to move.
    """
    emote = '\N{SNOWFLAKE}'

    def pre_turn_effect(self):
        super().pre_turn_effect()
        raise UserIsImmobilized


class Shock(_Ailment):
    """
    High chance of being immobilized. If you hit someone with your Attack, or they hit you with their Attack,
    there is a medium chance of them being inflicted with Shock.
    """
    emote = '\N{HIGH VOLTAGE SIGN}'

    def pre_turn_effect(self):
        super().pre_turn_effect()
        if random.randint(1, 10) != 1:
            raise UserIsImmobilized


class Dizzy(_Ailment):
    """
    Accuracy is severely reduced.
    """
    emote = '\N{DIZZY SYMBOL}'


class Hunger(_Ailment):
    """
    Attack power is greatly reduced.
    """
    emote = '\N{HAMBURGER}'


class Sleep(_Ailment):
    """
    You are unable to move, however your HP and SP will recover by 8% every turn. You have a high chance of waking if
    the enemy hits you with a physical attack.
    """
    emote = '\N{SLEEPING SYMBOL}'

    def pre_turn_effect(self):
        self.player.hp = -(self.player.max_hp*0.08)
        self.player.sp = -(self.player.max_sp*0.08)
        super().pre_turn_effect()
        raise UserIsImmobilized


class Fear(_Ailment, Exception):
    """
    High chance of being immobilized. Low chance of running away from battle.
    """
    emote = '\N{FACE SCREAMING IN FEAR}'

    def pre_turn_effect(self):
        super().pre_turn_effect()
        if random.randint(1, 10) != 1:
            raise UserIsImmobilized
        if random.randint(1, 10) == 1:
            raise self
