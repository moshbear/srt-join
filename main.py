# srt-join
#
# Copyright (c) 2022 Andrey V
# All rights reserved.
#
# This code is licensed under the 3-clause BSD License.
# See the LICENSE file at the root of this project.

from dataclasses import dataclass
from itertools import islice
from pathlib import Path
import re
from warnings import warn

def srt_timecode_to_msecs(tc: str) -> int:
    (hms, msec) = tc.split(',')
    msec = int(msec)
    (hour, min, sec) = [int(tok) for tok in hms.split(':')]
    return (msec +
        (sec * 1000) +
        (min * 1000 * 60) +
        (hour * 1000 * 60 * 60)
    )


def msecs_to_srt_timecode(xsecs: int) -> str:
    (xsecs, msec) = divmod(xsecs, 1000)
    (xsecs, sec) = divmod(xsecs, 60)
    (hour, min) = divmod(xsecs, 60)
    return f'{hour:02}:{min:02}:{sec:02},{msec:03}'

@dataclass
class SubtitleEntry:
    start: int
    end: int
    text: str

    def __str__(self):
        return f"SubtitleEntry({self.start} ({msecs_to_srt_timecode(self.start)})," \
               f" {self.end} ({msecs_to_srt_timecode(self.end)})," + \
               " " + ' * '.join(self.text.split('\n')) + ")"

def has_overlap(e1: SubtitleEntry, e2: SubtitleEntry) -> bool:
    # e1 [X] e2
    if e1.start <= e2.start and e1.end >= e2.start:
        return True
    # e2 [X] e1
    if e1.end >= e2.end and e1.start <= e2.end:
        return True
    # e2 in e1
    if e1.start <= e2.start and e1.end >= e2.end:
        return True
    # e1 in e2
    if e1.start >= e2.start and e1.end <= e2.end:
        return True
    return False

# Overlapping entries can be merged by earlier start time.
# This will misbehave if either entry is 2 lines but a warning is raised
# to notify the user.
def merge_entries(e1: SubtitleEntry, e2: SubtitleEntry) -> SubtitleEntry:
    begin = min(e1.start, e2.start)
    end = max(e1.end, e2.end)
    if begin == e1.start:
        text = e1.text + "\n" + e2.text
    else:
        text = e2.text + "\n" + e1.text
    return SubtitleEntry(begin, end, text)

@dataclass
class Input:
    filename: str
    skip_first: int = 0
    skip_last: int = 0

# tokenize the subtitle entries;
# declared index is stripped and substituted with list index
def read_subs(inp: Input) -> list[SubtitleEntry]:
    def _do_entry(token):
        pos_timecode = token.index(':')
        (idx, start, arrow, end, text) = re.split("\s", token, 4)
        if arrow != "-->":
            raise ValueError(f"at index {idx}: expected '-->'")
        return SubtitleEntry(srt_timecode_to_msecs(start), srt_timecode_to_msecs(end), text)
    subs = [_do_entry(tok) for tok in Path(inp.filename).read_text().split("\n\n") if tok]
    return islice(subs, inp.skip_first, len(subs) - inp.skip_last)

def print_entry(entry: SubtitleEntry, index: int) -> str:
    if entry.text.count("\n") > 1:
        warn(f"Excessive line count detected in entry {entry}")
    return f"{index}\n" \
           f"{msecs_to_srt_timecode(entry.start)} --> {msecs_to_srt_timecode(entry.end)}\n" + \
           entry.text

def main(in1: Input, in2: Input):
    subs1: list[Tuple[int, SubtitleEntry]] = enumerate(read_subs(in1))
    subs2: list[Tuple[int, SubtitleEntry]] = enumerate(read_subs(in2))
    i1 = iter(subs1)
    i2 = iter(subs2)
    s1 = next(i1, None)
    s2 = next(i2, None)
    new_idx = 0
    while s1 is not None or s2 is not None:
        new_idx += 1
        if s1 is not None and s2 is not None:
            did_print = False
            if has_overlap(s1[1], s2[1]):
                warn(f'overlap between file #1 index #{s1[0]} and ' \
                     f'file #2 index #{s2[0]}' \
                     f': {s1[1]} , {s2[1]}')
                print(print_entry(merge_entries(s1[1], s2[1]), new_idx), end="\n\n")
                did_print = True
            if s1[1].start < s2[1].start:
                if not did_print:
                    print(print_entry(s1[1], new_idx), end="\n\n")
                    did_print = True
                s1 = next(i1, None)
            else:
                if not did_print:
                    print(print_entry(s2[1], new_idx), end="\n\n")
                    did_print = True
                s2 = next(i2, None)
            continue
        while s1 is not None: # i2 exhausted; finish i1
            print(print_entry(s1[1], new_idx), end="\n\n")
            s1 = next(i1, None)
            new_idx += 1
        while s2 is not None: # i1 exhausted; finish i2
            print(print_entry(s2[1], new_idx), end="\n\n")
            s2 = next(i2, None)
            new_idx += 1


if __name__ == '__main__':
    from argparse import ArgumentParser, ArgumentTypeError
    _skipspec: dict[int, tuple[int, int]] = {}
    def _tokenize_skipspec(value: str) -> None:
        try:
            (spec, rest) = [v for v in value.split(':')]
            spec = int(spec)
            if spec not in range(1,3):
                raise ValueError(f'specifier out of range: {spec}')
            if spec in _skipspec:
                raise ValueError(f'specifier {spec} already used')
            s_first = 0
            s_last = 0
            for v in rest.split(','):
                if v[0] == '+':
                    if s_first == 0:
                        s_first = int(v[1:])
                        if s_first <= 0:
                            raise ValueError('skip-first: expected positive number')
                    else:
                        raise ValueError('skip-first (+) already specified')
                elif v[0] == '-':
                    if s_last == 0:
                        s_last = int(v[1:])
                        if s_last <= 0:
                            raise ValueError('skip-last: expected positive number')
                    else:
                        raise ValueError('skip-last (-) already specified')
                else:
                    raise ValueError(f'unrecognized specifier {v[0]}')
            _skipspec[spec] = (s_first, s_last)
        except ValueError as ve:
            raise ArgumentTypeError(f"parse error: {ve!s}") from ve
    parser = ArgumentParser()
    parser.add_argument('-s', action='append', type=_tokenize_skipspec)
    parser.add_argument('first')
    parser.add_argument('second')
    args = parser.parse_args()
    skip1 = _skipspec.get(1, (0,0))
    skip2 = _skipspec.get(2, (0,0))
    main(Input(args.first, skip1[0], skip1[1]), Input(args.second, skip2[0], skip2[1]))

    
