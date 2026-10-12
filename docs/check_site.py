"""Check that the published pages match the saved experiment evidence.

Verifies, using only the standard library:
- every result value marked with data-metric/data-value matches results.json,
  including its visible number and its count of filled segments;
- the Experiment 001 scenario matrix has all 24 runs, each matching results.json,
  and each cell's outcome style matches the recorded outcome;
- every embedded trace (data-trace) equals the recorded event list;
- every Part 2 total (data-exp="part2") equals the sum of the free-running
  runs in part-2-stress-test/results/results.json, including its visible number;
- relative links, in-page anchors, local assets, and links to files in this
  repository resolve.

Run from the repository root:  python3 docs/check_site.py
"""
import json
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / 'docs'
RESULTS = ROOT / 'experiments' / '001-memory-reliability' / 'results' / 'results.json'
RESULTS_PART2 = ROOT / 'experiments' / '001-memory-reliability' / 'part-2-stress-test' / 'results' / 'results.json'
SITE_URL = 'https://kishanssg.github.io/ai-thinking-lab/'
REPO_URL = 'https://github.com/kishanssg/ai-thinking-lab/'
EXPERIMENT_PAGE = DOCS / 'experiments' / '001-memory-reliability' / 'index.html'


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ids, self.links, self.metrics, self.cells, self.traces = set(), [], [], [], {}
        self._trace = None
        self._metric = None  # [attrs, depth, value text, filled, in value, segments]
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag not in VOID:
            self._depth += 1
        classes = a.get('class', '').split()
        if self._metric:
            if tag == 'i':
                self._metric[5] = (self._metric[5] or 0) + 1
                self._metric[3] += 'on' in classes
            if 'value' in classes:
                self._metric[4] = True
        if 'id' in a:
            self.ids.add(a['id'])
        for key in ('href', 'src'):
            if a.get(key):
                self.links.append(a[key])
        if tag == 'meta' and a.get('property') == 'og:image':
            self.links.append(a['content'])
        if 'data-metric' in a or 'data-exp' in a:
            self._metric = [a, self._depth, '', 0, False, None]
        if 'data-scenario' in a:
            self.cells.append(a)
        if 'data-trace' in a:
            self._trace = a['data-trace']
            self.traces[self._trace] = ''

    def handle_endtag(self, tag):
        if tag == 'pre':
            self._trace = None
        if self._metric and self._depth == self._metric[1]:
            a, _, text, filled, _, segments = self._metric
            self.metrics.append(dict(a, shown=text.strip(), filled=filled, segments=segments))
            self._metric = None
        elif self._metric and self._metric[4] and tag == 'span':
            self._metric[4] = False
        self._depth -= 1

    def handle_data(self, data):
        if self._trace:
            self.traces[self._trace] += data
        if self._metric and self._metric[4]:
            self._metric[2] += data


VOID = {'meta', 'link', 'br', 'img', 'input', 'hr', 'source', 'wbr'}


def outcome_class(run):
    """The scenario-matrix style implied by a recorded run."""
    eligible = next(e['state'] is True for e in run['events']
                    if e['kind'] == 'ground_truth' and e['phase'] == 'commit')
    if run['committed']:
        return 'o-write' if eligible else 'o-invalid'
    if eligible:
        return 'o-missed'
    return 'o-blocked' if run['recommended'] else 'o-refuse'


def parse(path):
    page = Page()
    page.feed(path.read_text(encoding='utf-8'))
    return page


def main():
    report = json.loads(RESULTS.read_text(encoding='utf-8'))
    summary = report['summary']
    runs = {(r['scenario'], r['approach']): r for r in report['runs']}
    pages = {p: parse(p) for p in sorted(DOCS.rglob('*.html'))}
    free = [r for r in json.loads(RESULTS_PART2.read_text(encoding='utf-8'))['runs'] if r['mode'] == 'free']
    totals_part2 = {a: (sum(r['approaches'][a]['invalid_commits']['numerator'] for r in free),
                       sum(r['approaches'][a]['invalid_commits']['denominator'] for r in free))
                   for a in free[0]['approaches']}
    errors, checked = [], {'metrics': 0, 'cells': 0, 'traces': 0, 'links': 0}

    for path, page in pages.items():
        name = path.relative_to(ROOT).as_posix()

        for m in page.metrics:
            if m.get('data-exp') == 'part2':
                n, d = totals_part2[m['data-approach']]
                label = f"{name}: part 2 {m['data-approach']}"
                if m['data-value'] != f'{n}/{d}':
                    errors.append(f"{label} is marked {m['data-value']}, part 2 results have {n}/{d}")
                if m['shown'] != f'{n:,} of {d:,}':
                    errors.append(f"{label} displays {m['shown']!r}, expected '{n:,} of {d:,}'")
                checked['metrics'] += 1
                continue
            s = summary[m['data-approach']][m['data-metric']]
            expected = f"{s['numerator']}/{s['denominator']}"
            label = f"{name}: {m['data-approach']} {m['data-metric']}"
            if m['data-value'] != expected:
                errors.append(f"{label} is marked {m['data-value']}, results.json has {expected}")
            if m['shown'] not in (expected, str(s['numerator'])):
                errors.append(f"{label} displays {m['shown']!r}, results.json has {expected}")
            if m['segments'] is not None and m['filled'] != s['numerator']:
                errors.append(f"{label} fills {m['filled']} segments, expected {s['numerator']}")
            if m['segments'] is not None and m['segments'] != s['denominator']:
                errors.append(f"{label} has {m['segments']} segments, expected {s['denominator']}")
            checked['metrics'] += 1

        seen = set()
        for c in page.cells:
            key = (c['data-scenario'], c['data-approach'])
            run = runs.get(key)
            shown = (c['data-recommended'] == 'true', c['data-committed'] == 'true')
            if run is None:
                errors.append(f'{name}: matrix cell {key} has no recorded run')
            elif shown != (run['recommended'], run['committed']):
                errors.append(f'{name}: matrix cell {key} shows {shown}, recorded '
                              f"{(run['recommended'], run['committed'])}")
            elif outcome_class(run) not in c.get('class', '').split():
                errors.append(f'{name}: matrix cell {key} is styled {c.get("class")}, '
                              f'expected {outcome_class(run)}')
            if key in seen:
                errors.append(f'{name}: matrix cell {key} appears twice')
            seen.add(key)
            checked['cells'] += 1
        if path == EXPERIMENT_PAGE and seen != set(runs):
            errors.append(f'{name}: matrix covers {len(seen)} of {len(runs)} runs')

        for key, text in page.traces.items():
            scenario, approach = key.split('/')
            if json.loads(text) != runs[(scenario, approach)]['events']:
                errors.append(f'{name}: trace {key} differs from results.json')
            checked['traces'] += 1

        for link in page.links:
            problem = check_link(path, link, pages)
            if problem:
                errors.append(f'{name}: {problem}')
            checked['links'] += 1

    print('Checked ' + ', '.join(f'{n} {k}' for k, n in checked.items()) +
          f' across {len(pages)} pages.')
    for error in errors:
        print('FAIL', error)
    return 1 if errors else 0


def check_link(page_path, link, pages):
    if link.startswith(SITE_URL):
        target = DOCS / link[len(SITE_URL):]
        return None if resolve(target) else f'missing site file for {link}'
    if link.startswith(REPO_URL):
        parts = urlsplit(link).path.split('/')[3:]  # ['blob'|'tree', branch, *path]
        if not parts:
            return None
        if parts[0] in ('blob', 'tree') and len(parts) > 2:
            target = ROOT.joinpath(*parts[2:])
            return None if target.exists() else f'repository path missing for {link}'
        return None
    url = urlsplit(link)
    if url.scheme or link.startswith('//') or link.startswith('mailto:'):
        return None
    target = resolve(page_path.parent / url.path) if url.path else page_path
    if target is None:
        return f'broken link {link}'
    if url.fragment:
        if target not in pages or url.fragment not in pages[target].ids:
            return f'missing anchor {link}'
    return None


def resolve(target):
    target = target.resolve()
    if target.is_dir():
        target = target / 'index.html'
    return target if target.exists() else None


if __name__ == '__main__':
    sys.exit(main())
