import ast
import json
import math
import os
import tempfile
import time
from pathlib import Path


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name, suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream)
        for attempt in range(8):
            try:
                os.replace(name, path)
                break
            except PermissionError as error:
                if getattr(error, 'winerror', None) not in (5, 32, 33) or attempt == 7:
                    raise
                time.sleep(0.01 * 2 ** attempt)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def save_model(path, table, schema, action_count):
    atomic_json(path, {'version': 2, 'schema': schema, 'actions': action_count, 'table': table})


def load_model(path, schema, action_count):
    payload = json.loads(Path(path).read_text())
    if payload.get('version') != 2 or payload.get('schema') != schema or payload.get('actions') != action_count:
        raise ValueError('Model schema/task mismatch; legacy tables require explicit offline migration')
    result = {}
    for key, values in payload['table'].items():
        state = ast.literal_eval(key)
        if not isinstance(state, tuple) or any(not isinstance(x, (int, bool)) for x in state):
            raise ValueError('Invalid observation key')
        if len(values) != action_count or any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
            raise ValueError('Invalid Q values')
        result[state] = list(values)
    return result


def model_compatible(path, schema, action_count):
    try:
        load_model(path, schema, action_count)
        return True
    except (OSError, ValueError, TypeError, KeyError, SyntaxError):
        return False


def mean_tables(tables):
    values = {}
    counts = {}
    for table in tables:
        for state, row in table.items():
            if state not in values:
                values[state] = [0.0] * len(row)
                counts[state] = 0
            counts[state] += 1
            values[state] = [a+b for a, b in zip(values[state], row)]
    return {state: [v/counts[state] for v in row] for state, row in values.items()}
