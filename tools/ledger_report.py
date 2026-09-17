"""Conservative scoped cash totals and observation reconciliation."""
from ledger import INCOME, EXPENSE


def totals(entries):
    result = {key: {'exact': 0, 'estimated': 0} for key in
              ('income', 'expenses', 'transfer_in', 'transfer_out', 'gift_in', 'gift_out', 'cash_result', 'movement')}
    for row in entries:
        direction, category, quality = row['direction'], row['category'], row['amount_quality']
        value = row['amount_copper']
        sign = 1 if direction == 'in' else -1
        if category in ('transfer', 'gift'):
            key = category + '_' + direction
        elif direction == 'in' and category in INCOME:
            key = 'income'
            result['cash_result'][quality] += value
        elif direction == 'out' and category in EXPENSE:
            key = 'expenses'
            result['cash_result'][quality] -= value
        else:
            continue
        result[key][quality] += value
        result['movement'][quality] += sign * value
    return result


def economy(entries, observations, void_ids, start, end, review=False):
    requested = [r for r in entries if start <= r['time'] < end]
    active = [r for r in requested if r['record_id'] not in void_ids]
    observed = [r for r in observations if start <= r['time'] <= end and type(r.get('gold')) is int and r['gold'] >= 0]
    observed.sort(key=lambda r: (r['time'], r['record_id']))
    result = dict(totals=totals(active), active=active,
                  voided=[r for r in requested if r['record_id'] in void_ids],
                  one_sided=[r for r in active if r['category'] == 'transfer'],
                  missing_cost=[r for r in active if r['category'] in ('craft','service') and r.get('player_material_cost_copper') is None],
                  estimated_cost=[r for r in active if r.get('material_cost_quality') == 'estimated'],
                  status='insufficient_observations', coverage='insufficient_observations',
                  opening=None, closing=None, raw=None, exact_residual=None, provisional_residual=None,
                  interval_totals=totals([]), boundary_ambiguous=False)
    if len(observed) < 2 or observed[0]['time'] == observed[-1]['time']:
        return result
    opening, closing = observed[0], observed[-1]
    first, last = opening['time'], closing['time']
    # With second-resolution source data, never pretend we know which transaction
    # preceded an observation in the same second. Such totals are provisional.
    boundary = any(r['time'] in (first,last) for r in entries if r['record_id'] not in void_ids)
    boundary |= any(len({r['gold'] for r in observed if r['time'] == t}) > 1 for t in (first,last))
    interval = [r for r in active if first <= r['time'] < last]
    sums = totals(interval)
    raw = closing['gold'] - opening['gold']
    exact = raw - sums['movement']['exact']
    provisional = exact - sums['movement']['estimated']
    coverage = 'complete' if first == start and last == end else 'partial_coverage'
    estimates = any(r['amount_quality'] == 'estimated' for r in interval)
    status = ('review_required' if review or boundary else 'provisional_estimates' if estimates else
              'partial_coverage' if coverage != 'complete' else 'unexplained' if exact else 'reconciled_exact')
    result.update(opening=opening,closing=closing,raw=raw,exact_residual=exact,
                  provisional_residual=provisional,coverage=coverage,status=status,
                  interval_totals=sums,boundary_ambiguous=boundary)
    return result


def render_economy(result, money, timestamp):
    lines = ['## Economy', '', '- Scope: requested report window and identity shown above.',
             '- The sections below are overlapping views of the same records, not additive totals. Only the observed-interval view is used for reconciliation.',
             f"- Coverage status: {result['coverage']}"]
    if result['opening']:
        lines += [f"- Observed interval: {timestamp(result['opening']['time'])} to {timestamp(result['closing']['time'])}",
                  f"- Opening observed balance: {money(result['opening']['gold'])}",
                  f"- Closing observed balance: {money(result['closing']['gold'])}",
                  f"- Raw balance change: {money(result['raw'])}"]
    else:
        lines += ['- Observed interval: unavailable', '- Opening/closing observed balance: insufficient observations',
                  '- Raw balance change: unavailable']
    labels = [('income','Classified income'),('expenses','Classified expenses'),
              ('transfer_in','Transfer inflow'),('transfer_out','Transfer outflow'),
              ('gift_in','Gift inflow'),('gift_out','Gift outflow'),
              ('cash_result','Recorded cash result'),('movement','Net classified balance movement')]
    for heading, sums in [('Requested-window totals',result['totals']),('Observed-interval totals [opening, closing)',result['interval_totals'])]:
        lines += ['', f'### {heading}', '']
        if heading.startswith('Observed') and not result['opening']:
            lines.append('- Unavailable: insufficient observations.')
            continue
        for key, label in labels:
            lines.append(f"- {label}: exact {money(sums[key]['exact'])}; estimated {money(sums[key]['estimated'])}")
    lines += ['', f"- Exact-only unexplained difference: {money(result['exact_residual']) if result['exact_residual'] is not None else 'unavailable'}",
              f"- Provisional unexplained difference: {money(result['provisional_residual']) if result['provisional_residual'] is not None else 'unavailable'}",
              f"- Reconciliation status: {result['status']}",
              f"- Same-second boundary ambiguity: {'yes; review required' if result['boundary_ambiguous'] else 'no'}",
              '- Tolerance: zero copper. Arithmetic agreement is not proof of classification.',
              '- Raw balance change is not profit. Cash result excludes gifts and transfers.',
              f"- Voided entries: {len(result['voided'])} (excluded retrospectively; original records retained)",
              f"- One-sided transfers: {len(result['one_sided'])} (unmatched; no counterpart inferred)",
              f"- Missing material costs (craft/service receipts): {len(result['missing_cost'])}",
              f"- Estimated material costs: {len(result['estimated_cost'])}"]
    for row in result['voided']:
        lines.append(f"- Voided entry: {row['record_id']} {row['direction']} {money(row['amount_copper'])} {row['category']}")
    for row in result['active']:
        cost = row.get('player_material_cost_copper')
        if cost is not None:
            quality = 'estimated' if 'estimated' in (row['amount_quality'],row['material_cost_quality']) else 'exact'
            lines.append(f"- Declared material margin [{row['record_id']}]: {money(row['amount_copper'] - cost)} ({quality}; not comprehensive profit)")
    lines += ['- Material annotations do not change cash totals or reconciliation.',
              '- Repeatable activity profit: unavailable; activity costs and duration are not established.', '']
    return lines
