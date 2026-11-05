from dataclasses import dataclass
from enum import Enum


class BattleOutcome(str, Enum):
    NONE = 'none'
    WIN = 'win'
    TRAINER_WIN = 'trainer_win'
    BLACKOUT = 'blackout'
    DISENGAGED = 'disengaged'
    UNKNOWN = 'unknown'


@dataclass(frozen=True)
class BattleSample:
    kind: int
    position: tuple[int, int, int]
    enemy_hp: int
    enemy_max: int
    party_hp: int


class BattleTracker:
    def __init__(self):
        self.reset()

    def reset(self):
        self.previous = None
        self.position = None
        self.saw_damage = False
        self.blacked_out = False
        self.knocked_out = False
        self.kind = 0
        self.wild_wins = 0
        self.trainer_wins = 0
        self.outcome = BattleOutcome.NONE

    def update(self, sample: BattleSample) -> BattleOutcome:
        previous = self.previous
        self.outcome = BattleOutcome.NONE
        if sample.kind:
            if previous is None or not previous.kind:
                self.position = sample.position
                self.saw_damage = self.knocked_out = self.blacked_out = False
                self.kind = sample.kind
            if previous and previous.party_hp > 0 and sample.party_hp == 0:
                self.blacked_out = True
            if previous and previous.kind and previous.enemy_hp > 0 and sample.enemy_hp == 0 and sample.enemy_max > 0:
                self.knocked_out = True
            self.previous = sample
            return self.outcome
        if previous and previous.kind:
            if sample.party_hp == 0 or self.blacked_out:
                self.outcome = BattleOutcome.BLACKOUT
            elif sample.position != self.position:
                self.outcome = BattleOutcome.UNKNOWN
            elif self.knocked_out and previous.enemy_hp == 0 and self.kind in (1, 2):
                if self.kind == 1:
                    self.outcome = BattleOutcome.WIN
                    self.wild_wins += 1
                else:
                    self.outcome = BattleOutcome.TRAINER_WIN
                    self.trainer_wins += 1
            else:
                self.outcome = BattleOutcome.DISENGAGED
        self.previous = sample
        return self.outcome


def retreat_allowed(hp: int, maximum: int, travel_priority: bool = False) -> bool:
    return travel_priority or maximum <= 0 or hp * 4 <= maximum


def battle_reward(outcome: BattleOutcome, *, safe_to_fight: bool, travel_priority: bool = False) -> float:
    if outcome in (BattleOutcome.WIN, BattleOutcome.TRAINER_WIN):
        return 0.0 if travel_priority else 0.5
    if outcome == BattleOutcome.BLACKOUT:
        return -1.0
    return 0.0


def potential_reward(before: float, after: float, gamma: float, terminated: bool) -> float:
    return gamma * (0.0 if terminated else after) - before
