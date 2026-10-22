"""Version 1 plan loading, including defaults for fields added in later releases."""
from dataclasses import asdict
from model import Settings, Work, Scenario, month_date, validate


def load_plan(raw):
    if not isinstance(raw, dict) or raw.get('version') != 1:
        raise ValueError('Fail peab olema selle rakenduse salvestatud plaan (versioon 1).')
    s = dict(raw['settings'])
    s['start'] = month_date(s['start'])
    # Dataclass defaults supply fields absent from previously saved version 1 plans.
    settings = Settings(**s)
    if settings.area < 1 or not -.2 <= settings.inflation <= .5 or not -.2 <= settings.construction <= .5:
        raise ValueError('Pindala peab olema vähemalt 1 m² ning hinnamuutused vahemikus −20 kuni 50%.')
    works = [Work(**{**w, 'deadline': month_date(w['deadline']) if w.get('deadline') else None}) for w in raw['works']]
    scenarios = [Scenario(**{**c, 'loan_date': month_date(c['loan_date']) if c.get('loan_date') else None}) for c in raw['scenarios']]
    if not 1 <= len(scenarios) <= 6 or len(works) > 100:
        raise ValueError('Plaanis võib olla 1–6 stsenaariumi ja kuni 100 tööd.')
    for c in scenarios:
        validate(settings, works, c)
        if c.interest > .3 or c.fee > .2:
            raise ValueError('Intress võib olla kuni 30% ja lepingutasu kuni 20%.')
    if len({c.name.strip() for c in scenarios}) != len(scenarios) or any(not c.name.strip() for c in scenarios):
        raise ValueError('Stsenaariumide nimed peavad olema erinevad ja mittetühjad.')
    return dict(settings=asdict(settings), works=[asdict(w) for w in works], scenarios=[asdict(c) for c in scenarios])
