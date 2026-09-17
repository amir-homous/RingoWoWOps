"""Phase 2A cash ledger validation. No valuation or transaction inference."""
import json
import re

MAX_COPPER = 2_147_483_647  # Deliberately below Lua's exact-integer ceiling.
INCOME = {'service', 'craft', 'sale', 'activity', 'refund', 'other'}
EXPENSE = {'repair', 'training', 'supplies', 'materials', 'purchase', 'fees', 'other'}
SPECIAL = {'transfer', 'gift', 'adjustment'}
QUALITIES = {'exact', 'estimated'}
LEDGER_DATASETS = ('ledger_entries', 'ledger_voids')
ENTRY_FIELDS = ('record_id', 'time', 'created_at', 'character', 'realm', 'session_id',
    'direction', 'category', 'amount_copper', 'amount_quality', 'input_source',
    'counterparty', 'note', 'activity', 'player_material_cost_copper',
    'material_cost_quality', 'material_provision', 'schema_version', 'addon_schema_version')
VOID_FIELDS = ('record_id', 'entry_id', 'time', 'created_at', 'character', 'realm',
    'input_source', 'reason', 'schema_version', 'addon_schema_version')
INT_FIELDS = {'time', 'created_at', 'amount_copper', 'player_material_cost_copper',
              'schema_version', 'addon_schema_version'}


def parse_money(token, allow_zero=False):
    quality = 'estimated' if token.startswith('~') else 'exact'
    value = token[1:] if quality == 'estimated' else token
    if not re.fullmatch(r'(?:[0-9]+[gG])?(?:[0-9]+[sS])?(?:[0-9]+[cC])?', value) or not value:
        raise ValueError('Use explicit ordered units, for example 12g50s')
    total = 0
    for number, unit in re.findall(r'([0-9]+)([gGsScC])', value):
        # Bound digit length before integer conversion (also matches Lua).
        number = number.lstrip('0') or '0'
        if len(number) > 10:
            raise ValueError('Amount exceeds safe copper bound')
        total += int(number) * {'g': 10000, 's': 100, 'c': 1}[unit.lower()]
    if total > MAX_COPPER or total < (0 if allow_zero else 1):
        raise ValueError('Amount outside supported copper range')
    return total, quality


def normalize_ledger(dataset, source):
    """Strict conversion only: never truncate fractional money or invent IDs."""
    row = dict(source)
    row['record_id'] = row.get('record_id') or row.get('id')
    for key in INT_FIELDS.intersection(row):
        value = row[key]
        if isinstance(value, str) and re.fullmatch(r'[0-9]+', value):
            row[key] = int(value) if len(value.lstrip('0')) <= 16 else value
        elif value == '':
            row[key] = None
    errors = []
    required = ('record_id', 'character', 'realm', 'input_source')
    for key in required:
        if not isinstance(row.get(key), str) or not row[key].strip():
            errors.append(f'{key}: nonempty text required')
    for key in ('time', 'created_at'):
        if type(row.get(key)) is not int or not 0 <= row[key] <= 9_007_199_254_740_991:
            errors.append(f'{key}: nonnegative integer Unix timestamp required')
    if type(row.get('schema_version')) is not int or type(row.get('addon_schema_version')) is not int or row.get('schema_version') != 1 or row.get('addon_schema_version') != 4:
        errors.append('unsupported ledger/addon schema version')
    if row.get('input_source') != 'addon_command':
        errors.append('input_source must be addon_command')
    fields = ENTRY_FIELDS if dataset == 'ledger_entries' else VOID_FIELDS
    for key in fields:
        if key not in INT_FIELDS and row.get(key) not in (None, '') and not isinstance(row[key], str):
            errors.append(f'{key}: text required')
    if errors:
        return row, errors
    if dataset == 'ledger_voids':
        if not row.get('entry_id') or not row.get('reason'):
            errors.append('void requires entry_id and reason')
    else:
        direction, category = row.get('direction'), row.get('category')
        if direction not in ('in', 'out') or category not in ((INCOME if direction == 'in' else EXPENSE) | SPECIAL):
            errors.append('invalid direction/category')
        if category == 'adjustment':
            errors.append('adjustment is reserved for future maintenance')
        amount = row.get('amount_copper')
        if type(amount) is not int or not 1 <= amount <= MAX_COPPER:
            errors.append('amount_copper must be a positive bounded integer')
        if row.get('amount_quality') not in QUALITIES:
            errors.append('invalid amount_quality')
        if category in ('gift', 'transfer') and not str(row.get('counterparty') or '').strip():
            errors.append('gift/transfer requires counterparty')
        cost = row.get('player_material_cost_copper')
        quality, provision = row.get('material_cost_quality'), row.get('material_provision')
        if cost is not None:
            if type(cost) is not int or not 0 <= cost <= MAX_COPPER or quality not in QUALITIES:
                errors.append('invalid material cost/quality')
        elif quality:
            errors.append('material quality requires cost')
        if provision and provision not in ('customer', 'player', 'mixed', 'unknown'):
            errors.append('invalid material provision')
        if provision == 'customer' and cost not in (None, 0):
            errors.append('customer materials cannot have player material cost')
        if (cost is not None or provision or quality) and not (direction == 'in' and category in ('service', 'craft', 'sale', 'activity', 'other')):
            errors.append('material annotations require an income receipt')
    return row, errors


def payload(dataset, row):
    fields = ENTRY_FIELDS if dataset == 'ledger_entries' else VOID_FIELDS
    return json.dumps({k: row.get(k) if row.get(k) != '' else None for k in fields},
                      sort_keys=True, ensure_ascii=False, separators=(',', ':'))
