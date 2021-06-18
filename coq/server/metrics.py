from concurrent.futures import FIRST_EXCEPTION, Future, wait
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from locale import strxfrm
from math import inf
from typing import Iterable, Iterator, MutableSequence, Sequence, Tuple, cast

from ..registry import pool
from ..shared.parse import is_word
from ..shared.settings import Options, Weights
from ..shared.types import Completion, Context
from .model.database import Database, SqlMetrics


class _ToleranceExceeded(Exception):
    pass


@dataclass(frozen=True)
class _MatchMetrics:
    prefix_matches: int
    match_density: float
    consecutive_matches: int
    num_matches: int


_ZERO = Weights(
    alphabetical=0,
    consecutive_matches=0,
    count_by_filetype=0,
    insertion_order=0,
    match_density=0,
    nearest_neighbour=0,
    num_matches=0,
    prefix_matches=0,
)


def _isjunk(s: str) -> bool:
    return s.isspace()


def _secondary(n_cword: str, n_match: str) -> _MatchMetrics:
    m = SequenceMatcher(a=n_cword, b=n_match, autojunk=True, isjunk=_isjunk)
    matches: MutableSequence[int] = []
    prefix_matches = 0
    num_matches = 0
    consecutive_matches = 0

    for ai, bi, size in m.get_matching_blocks():
        num_matches += size
        if ai == bi == 0:
            prefix_matches = size
        for i in range(bi, bi + size):
            matches.append(i)

    pm_idx = inf
    for i in matches:
        if pm_idx == i - 1:
            consecutive_matches += 1
        pm_idx = i

    match_density = num_matches / len(n_match) if n_match else 0
    metric = _MatchMetrics(
        prefix_matches=prefix_matches,
        consecutive_matches=consecutive_matches,
        match_density=match_density,
        num_matches=num_matches,
    )
    return metric


def _primary(
    transpose_band: int,
    cword: str,
    match: str,
    n_match: str,
) -> _MatchMetrics:

    idx = 0
    prefix_broken = False
    pm_idx = inf
    prefix_matches = 0
    consecutive_matches = 0
    num_matches = 0

    for i, char in enumerate(cword):
        if i > transpose_band and not num_matches:
            raise _ToleranceExceeded()
        else:
            target = match if char.isupper() else n_match
            m_idx = target.find(char, idx, idx + transpose_band)

            if m_idx != -1:
                if pm_idx == m_idx - 1:
                    consecutive_matches += 1
                num_matches += 1
                pm_idx = m_idx
                idx = m_idx + 1
            if m_idx != i:
                prefix_broken = True
            if not prefix_broken:
                prefix_matches += 1

    match_density = num_matches / len(match) if match else 0
    metric = _MatchMetrics(
        prefix_matches=prefix_matches,
        consecutive_matches=consecutive_matches,
        match_density=match_density,
        num_matches=num_matches,
    )
    return metric


def _metrics(
    options: Options, context: Context, completions: Iterable[Completion]
) -> Iterator[_MatchMetrics]:
    w_before = context.words_before, context.words_before.casefold()
    sw_before = context.syms_before, context.syms_before.casefold()

    for completion in completions:
        edit = completion.primary_edit
        match, n_match = edit.new_text, edit.new_text.casefold()
        word_start = is_word(match[:1], unifying_chars=options.unifying_chars)
        cword, n_cword = w_before if word_start else sw_before

        try:
            yield _primary(
                options.transpose_band, cword=cword, match=match, n_match=n_match
            )
        except _ToleranceExceeded:
            yield _secondary(n_cword, n_match=n_match)


def _weights(
    metrics: Iterable[Tuple[Completion, SqlMetrics, _MatchMetrics]]
) -> Iterator[Tuple[Completion, Weights]]:
    for cmp, sql, match in metrics:
        weight = Weights(
            alphabetical=0,
            consecutive_matches=match.consecutive_matches,
            count_by_filetype=sql["ft_count"],
            insertion_order=sql["insertion_order"],
            match_density=match.match_density,
            nearest_neighbour=sql["line_diff"],
            num_matches=match.num_matches,
            prefix_matches=match.prefix_matches,
        )
        yield cmp, weight


def _cum(adjustment: Weights, weights: Iterable[Weights]) -> Weights:
    acc = asdict(_ZERO)
    for weight in weights:
        for key, val in asdict(weight).items():
            acc[key] += val
    for key, val in asdict(adjustment).items():
        acc[key] *= val
    return Weights(**acc)


def _sorted(
    cum: Weights, it: Iterable[Tuple[Completion, Weights]]
) -> Sequence[Tuple[Completion, Weights]]:
    adjustment = asdict(cum)

    def key_by(single: Tuple[Completion, Weights]) -> float:
        _, weight = single
        tot = sum(
            val / adjustment[key] if adjustment[key] else 0
            for key, val in asdict(weight).items()
        )
        return tot

    return sorted(it, key=key_by, reverse=True)


from json import dump

from std2.pickle import encode
from std2.pickle.coders import BUILTIN_ENCODERS

from ..consts import TMP_DIR


def rank(
    options: Options,
    weights: Weights,
    db: Database,
    context: Context,
    completions: Sequence[Completion],
) -> Iterator[Completion]:
    def c1() -> Sequence[SqlMetrics]:
        words = (comp.sort_by or comp.primary_edit.new_text for comp in completions)
        row, _ = context.position
        return db.metric(
            words,
            filetype=context.filetype,
            filename=context.filename,
            line_num=row,
        )

    def c2() -> Sequence[_MatchMetrics]:
        return tuple(_metrics(options, context=context, completions=completions))

    f1, f2 = pool.submit(c1), pool.submit(c2)
    wait((cast(Future, f1), cast(Future, f2)), return_when=FIRST_EXCEPTION)
    metrics = zip(completions, f1.result(), f2.result())

    individual = tuple(_weights(metrics))
    cum = _cum(weights, weights=(w for _, w in individual))
    ordered = _sorted(cum, it=individual)

    with open(TMP_DIR / "log.json", "w") as fd:
        thing = {
            "ADJ": asdict(cum),
            "CMP": tuple(
                {"C": encode(c, encoders=BUILTIN_ENCODERS), "W": asdict(w)}
                for c, w in ordered
            ),
        }
        dump(thing, fd)

    return (c for c, _ in ordered)

