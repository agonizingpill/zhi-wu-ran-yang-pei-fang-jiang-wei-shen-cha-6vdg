"""Measured-swatch learning for shade remake suggestions.

The model is deliberately small and auditable: every measured swatch belongs to
a recipe group (its concentration triple is the recipe concentration).  Groups
are fitted with a ridge regression from the three dye concentrations to CIELAB,
and validated by leaving out *whole recipe groups* in turn.  The suggestion for
a target shade is the bounded least-squares concentration triple: it minimises
the predicted colour difference with each dye capped by the caller, while a mild
pull toward the nearest measured group keeps the answer inside known practice.

No database or HTTP concerns live here; ``suggestion_service`` snapshots rows and
hands plain dictionaries to :func:`evaluate`.
"""
import math

import numpy as np

COLOUR_THRESHOLD = 3.0
RIDGE = 1e-6
PRIOR_WEIGHT = 20.0
MIN_GROUPS = 4
MIN_GROUP_SAMPLES = 1
LAB_KEYS = ('l', 'a', 'b')
DYE_KEYS = ('dye_a', 'dye_b', 'dye_c')
METHOD = '同配方整组留出 → 标准化浓度岭回归 → 有界最小二乘 / 门限 3.000'


def colour_difference(left, right):
    """CIEDE76 for two Lab mappings/sequences."""
    if isinstance(left, dict):
        left = [left[k] for k in LAB_KEYS]
    if isinstance(right, dict):
        right = [right[k] for k in LAB_KEYS]
    return math.sqrt(sum((float(x) - float(y)) ** 2 for x, y in zip(left, right)))


def group_samples(training):
    """Group measured samples by recipe; the group keeps one concentration."""
    grouped = {}
    for row in training:
        code = str(row['group'])
        grouped.setdefault(code, []).append(row)
    groups = []
    for code in sorted(grouped):
        rows = grouped[code]
        concentration = [float(rows[0][key]) for key in DYE_KEYS]
        labs = np.array([[float(r[key]) for key in LAB_KEYS] for r in rows], dtype=float)
        groups.append({
            'group': code,
            'samples': len(rows),
            'concentration': concentration,
            'lab': labs.mean(axis=0).tolist(),
            'labels': [r.get('lot', '') for r in rows],
            # A recipe's concentration is fixed at intake; a mismatch means the
            # snapshot was assembled incorrectly, so it is reported upstream.
            'consistent': all(
                max(abs(float(r[key]) - value) for key, value in zip(DYE_KEYS, concentration)) <= 1e-9
                for r in rows
            ),
        })
    return groups


def _design(groups):
    concentrations = np.array([g['concentration'] for g in groups], dtype=float)
    labels = np.array([g['lab'] for g in groups], dtype=float)
    return concentrations, labels


def _fit(groups):
    concentrations, labels = _design(groups)
    mean = concentrations.mean(axis=0)
    scale = concentrations.std(axis=0)
    scale = np.where(scale < 1e-9, 1.0, scale)
    design = np.column_stack([np.ones(len(groups)), (concentrations - mean) / scale])
    gram = design.T @ design + RIDGE * np.eye(design.shape[1])
    weights = np.linalg.solve(gram, design.T @ labels)
    return {'mean': mean, 'scale': scale, 'weights': weights}


def _raw_parameters(model):
    """Convert standardised coefficients back to raw concentration units.

    Returns ``(intercept, slope)`` where ``slope`` is shaped Lab × dye so a
    concentration vector maps as ``intercept + slope @ concentration``.
    """
    weights = model['weights']
    slope = (weights[1:] / model['scale'][:, None]).T
    intercept = weights[0] - (model['mean'] / model['scale']) @ weights[1:]
    return intercept, slope


def _predict(model, concentration):
    values = np.asarray(concentration, dtype=float)
    scaled = (values - model['mean']) / model['scale']
    return model['weights'][0] + scaled @ model['weights'][1:]


def holdout(groups):
    """Leave one whole recipe group out at a time and score its centroid."""
    rows = []
    for held in groups:
        rest = [g for g in groups if g['group'] != held['group']]
        if len(rest) < MIN_GROUPS - 1:
            continue
        model = _fit(rest)
        predicted = _predict(model, held['concentration'])
        rows.append({
            'group': held['group'],
            'samples': held['samples'],
            'concentration': [round(v, 4) for v in held['concentration']],
            'measured_l': round(held['lab'][0], 3),
            'measured_a': round(held['lab'][1], 3),
            'measured_b': round(held['lab'][2], 3),
            'predicted_l': round(float(predicted[0]), 3),
            'predicted_a': round(float(predicted[1]), 3),
            'predicted_b': round(float(predicted[2]), 3),
            'delta_e': round(float(np.linalg.norm(predicted - np.array(held['lab']))), 4),
        })
    maximum = max((row['delta_e'] for row in rows), default=None)
    return {'threshold': COLOUR_THRESHOLD, 'max_delta_e': maximum, 'groups': rows}


def _nearest_prior(groups, target, caps):
    """Use the closest measured shade as a practical starting point."""
    if not groups:
        return np.zeros(3)
    nearest = min(groups, key=lambda g: colour_difference(g['lab'], target))
    return np.clip(np.array(nearest['concentration'], dtype=float), 0.0, caps)


def _bounded_solution(slope, intercept, target, caps, prior):
    """Exhaust the 3^3 active sets; exact for a convex quadratic objective."""
    target = np.asarray(target, dtype=float)
    gram = slope.T @ slope + PRIOR_WEIGHT * np.eye(3)
    rhs = slope.T @ (target - intercept) + PRIOR_WEIGHT * prior
    best = None
    for codes in np.ndindex(3, 3, 3):
        candidate = np.zeros(3)
        free, fixed = [], {}
        for axis, code in enumerate(codes):
            if code == 0:
                free.append(axis)
            elif code == 1:
                candidate[axis] = caps[axis]
                fixed[axis] = caps[axis]
            else:
                fixed[axis] = 0.0
        if free:
            block = gram[np.ix_(free, free)]
            right = rhs[free].copy()
            for axis, value in fixed.items():
                right -= gram[free, axis] * value
            try:
                solution = np.linalg.solve(block, right)
            except np.linalg.LinAlgError:
                continue
            if any(solution[i] < -1e-9 or solution[i] > caps[axis] + 1e-9
                   for i, axis in enumerate(free)):
                continue
            for i, axis in enumerate(free):
                candidate[axis] = solution[i]
        candidate = np.clip(candidate, 0.0, caps)
        predicted = intercept + slope @ candidate
        delta = float(np.linalg.norm(predicted - target))
        penalty = float(np.linalg.norm(candidate - prior))
        # Colour fit dominates; the prior only breaks ties between concentrations
        # that reach the target equally well, so it never trades away colour.
        if best is None or (round(delta, 6), penalty) < (round(best[0], 6), best[1]):
            best = (delta, penalty, candidate, predicted)
    return best


def _refusal(reason, **extra):
    result = {
        'verdict': 'refused',
        'refusal_reason': reason,
        'prediction': None,
        'predicted_delta_e': None,
        'holdout': None,
        'method': METHOD,
    }
    result.update(extra)
    return result


def evaluate(training, target, limits):
    """Learn from measured swatches and suggest capped dye concentrations.

    ``training`` is a list of dicts with ``group`` (recipe code), ``lot``,
    ``dye_a/dye_b/dye_c`` and ``l/a/b``.  ``target`` is ``{'l','a','b'}`` and
    ``limits`` is ``{'dye_a','dye_b','dye_c'}``.  A refused result never carries
    a concentration triple.
    """
    target = np.array([float(target[key]) for key in LAB_KEYS], dtype=float)
    caps = np.array([float(limits[key]) for key in DYE_KEYS], dtype=float)
    groups = group_samples(training)
    base = {'group_count': len(groups), 'training_count': len(training)}
    if not groups or len(groups) < MIN_GROUPS:
        return _refusal(f'训练配方组不足（{len(groups)} 组，至少 {MIN_GROUPS} 组），不能整组留出检验', **base)
    if any(g['samples'] < MIN_GROUP_SAMPLES for g in groups):
        return _refusal('存在没有实测染样的配方组，不能整组留出检验', **base)
    if not all(g['consistent'] for g in groups):
        return _refusal('训练快照内同一配方出现不同浓度，不能学习浓度关系', **base)
    concentrations = np.array([g['concentration'] for g in groups], dtype=float)
    flat = [key for axis, key in enumerate(DYE_KEYS) if concentrations[:, axis].std() < 1e-9]
    if flat:
        return _refusal(f'训练样本中染料 {"/".join(x[-1].upper() for x in flat)} 浓度没有变化，无法学习其影响', **base)

    model = _fit(groups)
    report = holdout(groups)
    base['holdout'] = report

    labels = np.array([[float(row[key]) for key in LAB_KEYS] for row in training], dtype=float)
    low, high = labels.min(axis=0), labels.max(axis=0)
    coverage = [
        {'key': key, 'min': round(float(low[i]), 3), 'max': round(float(high[i]), 3)}
        for i, key in enumerate(LAB_KEYS)
    ]
    outside = [
        f'{key.upper()}={target[i]:.2f}（训练范围 {low[i]:.2f}–{high[i]:.2f}）'
        for i, key in enumerate(LAB_KEYS)
        if target[i] < low[i] - 1e-9 or target[i] > high[i] + 1e-9
    ]

    intercept, slope = _raw_parameters(model)
    prior = _nearest_prior(groups, target, caps)
    solved = _bounded_solution(slope, intercept, target, caps, prior)
    if solved is None:  # pragma: no cover - caps are positive, so a corner always exists
        return _refusal('三染料上限内找不到可行浓度组合', **base)
    _delta, _penalty, candidate, predicted = solved
    rounded = np.round(np.clip(candidate, 0.0, caps), 4)
    predicted = intercept + slope @ rounded
    delta = float(np.linalg.norm(predicted - target))
    base['predicted_delta_e'] = round(delta, 4)
    base['coverage'] = coverage
    if outside:
        return _refusal('目标色超出训练范围：' + '，'.join(outside), **base)
    if report['max_delta_e'] is not None and report['max_delta_e'] > COLOUR_THRESHOLD:
        return _refusal(
            f'整组留出检验最大色差 {report["max_delta_e"]:.3f} 超过 3.000，模型不足以给出浓度',
            **base,
        )
    if delta > COLOUR_THRESHOLD:
        return _refusal(
            f'三染料上限内预测色差 {delta:.3f} 超过 3.000，无法达到目标色',
            **base,
        )
    return {
        'verdict': 'suggested',
        'refusal_reason': '',
        'prediction': {
            'dye_a': round(float(rounded[0]), 4),
            'dye_b': round(float(rounded[1]), 4),
            'dye_c': round(float(rounded[2]), 4),
            'predicted_l': round(float(predicted[0]), 3),
            'predicted_a': round(float(predicted[1]), 3),
            'predicted_b': round(float(predicted[2]), 3),
            'nearest_group': min(groups, key=lambda g: colour_difference(g['lab'], target))['group'],
        },
        'predicted_delta_e': round(delta, 4),
        'holdout': report,
        'coverage': coverage,
        'method': METHOD,
        'group_count': len(groups),
        'training_count': len(training),
    }
