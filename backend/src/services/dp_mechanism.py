"""Pure helpers for the differentially private grade-frequency release.

The release is a k x 9 histogram (treatment x grade).  Adjacency is bounded
replacement of one specimen record inside the study (grade and/or treatment
label; the number of specimens does not change).  Such a replacement can
change at most two cells by one, so the L1 sensitivity of the full table is 2.
Adding independent Laplace(0, 2/epsilon) noise to every cell therefore gives
pure epsilon-DP for the whole table.
"""
import hashlib
import json
import math
import random
from decimal import Decimal, InvalidOperation

DP_MECHANISM = 'laplace-vector-v1'
DP_ADJACENCY = 'bounded-replacement-one-specimen-record'
DP_SENSITIVITY_L1 = 2
DP_GRADES = tuple(range(1, 10))
DP_MICROS = 1_000_000
DP_MAX_MICROS = 1_000 * DP_MICROS
DP_ADJACENCY_EXPLANATION = (
    '邻接关系：在同一研究内替换一份独立试样记录（改变其形成等级和/或所属预定义工艺），'
    '试样总数保持不变。一次替换最多使一个工艺等级格减1、另一个格加1，故整张工艺×等级'
    '频数表的L1敏感度为2。'
)
DP_DISCLOSURE = (
    '仅发布按研究预设总ε加噪的各工艺等级频数。每个等级格独立加Laplace(0, 2/ε)噪声；'
    '加噪频数可为负、非整数，不能读作真实试样数、比例或工艺优劣，也不得与发布表之外的'
    '数据拼接推断个体。逐份等级、原始频数与精确检验只保留在内部分析中。'
    '发布身份按加噪结果本身计算，冻结输入的摘要仅在服务端用于去重、不对外提供。'
)


def epsilon_to_micros(value, label='ε'):
    """Convert an epsilon to exact millionths; reject sub-micro precision."""
    if isinstance(value, bool) or value is None:
        raise ValueError(f'{label}必须为正数')
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f'{label}必须为有限正数')
    if not dec.is_finite() or dec <= 0:
        raise ValueError(f'{label}必须为有限正数')
    micros = dec * Decimal(DP_MICROS)
    if micros != micros.to_integral_value():
        raise ValueError(f'{label}最多支持6位小数')
    micros = int(micros)
    if micros < 1:
        raise ValueError(f'{label}过小，至少为0.000001')
    if micros > DP_MAX_MICROS:
        raise ValueError(f'{label}过大，最多为1000')
    return micros


def micros_to_epsilon(micros):
    return int(micros) / DP_MICROS


def result_fingerprint(snapshot, epsilon_micros):
    """Server-side only: identity of the frozen input.

    This digest is a deterministic function of the raw specimens.  Exposing it
    would let a holder of a candidate dataset confirm individual grades offline
    and would void the differential-privacy guarantee, so it is never returned
    by the API or written to a distributed artifact.
    """
    treatments = sorted(snapshot['treatments'], key=lambda t: t['code'])
    readings = sorted(snapshot['readings'], key=lambda r: (r['specimen_code'], r['treatment_code'], r['grade']))
    canonical = {
        'algorithm': 'dp-grade-histogram-release-v1',
        'mechanism': DP_MECHANISM,
        'adjacency': DP_ADJACENCY,
        'sensitivity_l1': DP_SENSITIVITY_L1,
        'epsilon_micros': int(epsilon_micros),
        'grade_domain': list(DP_GRADES),
        'study_code': snapshot['study']['code'],
        'treatments': [[t['code'], t['name']] for t in treatments],
        'readings': [[r['specimen_code'], r['treatment_code'], r['grade']] for r in readings],
    }
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def release_digest(result):
    """Public identity of an already-noised release (post-processing only)."""
    public = {k: v for k, v in result.items() if k not in ('publication_id', 'release_digest')}
    return hashlib.sha256(json.dumps(public, sort_keys=True, separators=(',', ':'), allow_nan=False, ensure_ascii=False).encode()).hexdigest()


def laplace_noise(rng, scale):
    """Inverse-CDF Laplace draw; avoids log(0) and needs no SciPy."""
    while True:
        u = rng.random()
        if 0.0 < u < 1.0:
            break
    magnitude = -scale * math.log(1.0 - 2.0 * abs(u - 0.5))
    return magnitude if u >= 0.5 else -magnitude


def noisy_grade_table(snapshot, epsilon_micros, noise_seed):
    """Deterministic from (snapshot, epsilon, seed); never touches the database."""
    epsilon = micros_to_epsilon(epsilon_micros)
    scale = DP_SENSITIVITY_L1 / epsilon
    rng = random.Random(int(noise_seed))
    treatments = []
    for treatment in sorted(snapshot['treatments'], key=lambda t: t['code']):
        cells = [{'grade': grade, 'noisy_count': round(laplace_noise(rng, scale), 6)} for grade in DP_GRADES]
        treatments.append({'code': treatment['code'], 'name': treatment['name'], 'noisy_counts': cells})
    return {
        'mechanism': DP_MECHANISM,
        'adjacency': DP_ADJACENCY,
        'adjacency_explanation': DP_ADJACENCY_EXPLANATION,
        'sensitivity_l1': DP_SENSITIVITY_L1,
        'epsilon': epsilon,
        'epsilon_micros': int(epsilon_micros),
        'noise_scale': scale,
        'grade_domain': list(DP_GRADES),
        'treatments': treatments,
        'disclosure': DP_DISCLOSURE,
    }
