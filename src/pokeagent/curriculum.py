from dataclasses import dataclass
from pathlib import Path
import json


@dataclass(frozen=True)
class SkillSpec:
    name: str
    prerequisites: tuple[str, ...]
    evidence: str
    enabled: bool = False


SKILLS = (
    SkillSpec('menu_start', (), 'START menu signature then return to overworld'),
    SkillSpec('menu_items', ('menu_start',), 'ITEM menu signature and selected item identity'),
    SkillSpec('menu_party', ('menu_start',), 'party menu signature and selected party slot'),
    SkillSpec('shop_buy', ('menu_items',), 'item quantity increases and money decreases'),
    SkillSpec('shop_sell', ('menu_items',), 'selected item decreases and money increases'),
    SkillSpec('heal', (), 'damaged party HP restored and status cleared after interaction'),
    SkillSpec('trade', ('menu_party',), 'requested species exchanged and received species verified'),
    SkillSpec('special_event', (), 'event-specific before/after RAM evidence'),
    SkillSpec('elite4', ('heal', 'battle'), 'eight badges, eligible team, ordered victory flags'),
)


def mastered(record, *, segment, schema=None, minimum=24, threshold=0.9):
    if record.get('version') != 2 or record.get('success_definition') != 2:
        return False
    if record.get('segment') != segment or (schema and record.get('schema') != schema):
        return False
    episodes, wins = record.get('episodes', 0), record.get('wins', -1)
    return (isinstance(episodes, int) and isinstance(wins, int) and episodes >= minimum
            and 0 <= wins <= episodes and wins / episodes >= threshold
            and record.get('epsilon') == 0 and bool(record.get('git_sha'))
            and bool(record.get('model_digest')) and bool(record.get('source_digest')))


def stage_cleared(segment, root='runs'):
    root = Path(root)
    if not (root / 'checkpoints' / f'rl_{segment}.state').exists():
        return False
    for path in root.glob(f'eval_{segment}_*.json'):
        try:
            if mastered(json.loads(path.read_text()), segment=segment):
                return True
        except (OSError, ValueError, TypeError):
            continue
    return False
