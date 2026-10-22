"""Monthly, deterministic housing association funding model. No external dependencies."""
from dataclasses import dataclass, field
from datetime import date
from math import isfinite


def month_date(value):
    if isinstance(value, str):
        value = date.fromisoformat(value)
    return date(value.year, value.month, 1)


def add_months(value, months):
    n = value.year * 12 + value.month - 1 + months
    return date(n // 12, n % 12 + 1, 1)


@dataclass
class Work:
    name: str
    cost: float
    annual_loss: float = 0
    deadline: date | None = None


@dataclass
class Settings:
    area: float = 2000
    initial_cash: float = 0
    inflation: float = .03
    construction: float = .04
    years: int = 25
    start: date = date(2026, 10, 1)
    deposit_rate: float = .027


@dataclass
class Scenario:
    name: str
    rate: float = 1
    months: list[int] = field(default_factory=lambda: list(range(1, 13)))
    index_contributions: bool = False
    loan_mode: str = "none"
    interest: float = .05
    term_years: int = 15
    fee: float = .01
    loan_limit: float = 500000
    loan_date: date | None = None
    loan_amount: float = 0
    extra_repayment: bool = False


def payment(principal, annual_interest, months):
    r = annual_interest / 12
    return principal / months if r == 0 else principal * r / (1 - (1 + r) ** -months)


def validate(settings, works, scenario):
    def number(value, label, low=0, high=float('inf')):
        if not isinstance(value, (int, float)) or not isfinite(value) or not low <= value <= high:
            raise ValueError(f"{label}: väärtus peab olema vahemikus {low} kuni {high}.")
    number(settings.area, "Pindala", .01)
    number(settings.initial_cash, "Algsaldo")
    number(settings.deposit_rate, "Hoiuseintress", 0, 1)
    number(settings.inflation, "Inflatsioon", -.5, 1)
    number(settings.construction, "Ehitushinna kasv", -.5, 1)
    number(settings.years, "Periood", 1, 50)
    number(scenario.rate, "Kogumismäär")
    number(scenario.interest, "Laenuintress", 0, 1)
    number(scenario.term_years, "Laenuperiood", 1, 40)
    number(scenario.fee, "Lepingutasu", 0, .5)
    number(scenario.loan_limit, "Laenulimiit")
    number(scenario.loan_amount, "Laenusumma")
    if int(settings.years) != settings.years or int(scenario.term_years) != scenario.term_years:
        raise ValueError("Periood peab olema täisarv aastates.")
    if any(m not in range(1, 13) for m in scenario.months) or len(set(scenario.months)) != len(scenario.months):
        raise ValueError("Kogumiskuud peavad olema kordumatud kuud 1–12.")
    if scenario.loan_mode not in ("none", "deadline", "fixed"):
        raise ValueError("Tundmatu laenuviis.")
    if scenario.loan_mode == "fixed" and scenario.loan_date is None:
        raise ValueError("Määra laenu võtmise kuu.")
    if scenario.loan_date and month_date(scenario.loan_date) < month_date(settings.start):
        raise ValueError("Laenu kuupäev ei tohi olla enne arvutuse algust.")
    if not works:
        raise ValueError("Lisa vähemalt üks töö.")
    for w in works:
        if not isinstance(w.name, str) or not w.name.strip():
            raise ValueError("Igal tööl peab olema nimi.")
        number(w.cost, "Töö maksumus")
        number(w.annual_loss, "Tegemata töö aastakulu")


def simulate(settings, works, scenario):
    validate(settings, works, scenario)
    start = month_date(settings.start)
    growth = 1 + settings.construction
    cash = settings.initial_cash
    loans, events, rows = [], [], []
    completed = {}
    totals = dict(contributions=0., extra=0., repairs=0., losses=0., interest=0., fees=0., borrowed=0., deposit_income=0.)
    real_cost = 0.
    real_deposit_income = 0.
    deadlines = [month_date(w.deadline) if w.deadline else None for w in works]
    # Preserve past deadlines for lateness reporting; they are due immediately.
    # A later work's deadline also applies to its unfinished predecessors.
    effective = [min((d for d in deadlines[i:] if d), default=None) for i in range(len(works))]
    minimum_cash = cash
    for t in range(int(settings.years) * 12):
        current = add_months(start, t)
        price_factor = growth ** (t / 12)
        inflation_factor = (1 + settings.inflation) ** (t / 12)
        # Cash flows settle at month end; only the positive opening cash earns interest.
        deposit_income = max(0., cash) * settings.deposit_rate / 12
        cash += deposit_income
        totals['deposit_income'] += deposit_income
        real_deposit_income += deposit_income / inflation_factor
        contribution = settings.area * scenario.rate * (inflation_factor if scenario.index_contributions else 1) if current.month in scenario.months else 0
        cash += contribution
        totals['contributions'] += contribution
        principal_paid = interest_paid = debt_service = 0.
        for loan in loans:
            if loan['balance'] <= 1e-8:
                continue
            interest = loan['balance'] * scenario.interest / 12
            principal = min(loan['balance'], max(0, loan['payment'] - interest))
            loan['balance'] -= principal
            loan['remaining'] -= 1
            interest_paid += interest
            principal_paid += principal
        debt_service = principal_paid + interest_paid
        extra = debt_service if scenario.extra_repayment else 0.
        cash += extra - debt_service
        totals['extra'] += extra
        totals['interest'] += interest_paid
        # Pending work incurs one twelfth of its annual cost, including execution month.
        losses = sum(w.annual_loss for i, w in enumerate(works) if i not in completed) * inflation_factor / 12
        cash -= losses
        totals['losses'] += losses
        fee_this_month = borrowed = repairs = 0.

        def borrow(amount, reason):
            nonlocal cash, fee_this_month, borrowed
            amount = max(0., min(amount, scenario.loan_limit - totals['borrowed']))
            if amount < .005:
                return
            fee = amount * scenario.fee
            pmt = payment(amount, scenario.interest, int(scenario.term_years) * 12)
            loans.append(dict(balance=amount, payment=pmt, remaining=int(scenario.term_years) * 12))
            cash += amount - fee
            borrowed += amount
            fee_this_month += fee
            totals['borrowed'] += amount
            totals['fees'] += fee
            events.append(dict(date=current, amount=amount, fee=fee, payment=pmt,
                               maturity=add_months(current, int(scenario.term_years) * 12), reason=reason))

        if scenario.loan_mode == 'fixed' and current == month_date(scenario.loan_date):
            borrow(scenario.loan_amount, 'Määratud laen')
        for i, work in enumerate(works):
            if i in completed:
                continue
            cost = work.cost * price_factor
            if cash + 1e-7 < cost and scenario.loan_mode == 'deadline' and effective[i] and current >= effective[i]:
                borrow((cost - cash) / (1 - scenario.fee), work.name)
            if cash + 1e-7 < cost:
                break
            cash -= cost
            repairs += cost
            totals['repairs'] += cost
            completed[i] = dict(name=work.name, date=current, cost=cost,
                                real_cost=cost / inflation_factor, deadline=deadlines[i],
                                on_time=deadlines[i] is None or current <= deadlines[i])
        minimum_cash = min(minimum_cash, cash)
        real_cost += (repairs + losses + interest_paid + fee_this_month) / inflation_factor
        debt = sum(l['balance'] for l in loans)
        rows.append(dict(date=current, cash=cash, debt=debt, net=cash-debt,
                         deposit_income=deposit_income, cumulative_deposit_income=totals['deposit_income'],
                         contributions=contribution, extra=extra, losses=losses, repairs=repairs,
                         borrowed=borrowed, fees=fee_this_month, interest=interest_paid,
                         principal=principal_paid, debt_service=debt_service,
                         household_payment=contribution + extra,
                         completed=len(completed), paid_cost=totals['repairs'] + totals['losses'] + totals['interest'] + totals['fees']))
    future_interest = max(0., sum(l['payment'] * l['remaining'] - l['balance'] for l in loans))
    all_done = len(completed) == len(works)
    return dict(rows=rows, completed=completed, loans=events, totals=totals,
                future_interest=future_interest, total_cost=rows[-1]['paid_cost'] + future_interest,
                net_cost=rows[-1]['paid_cost'] + future_interest - totals['deposit_income'],
                real_net_cost=real_cost - real_deposit_income,
                real_cost=real_cost, minimum_cash=minimum_cash, feasible=minimum_cash >= -.01,
                all_done=all_done, finish=max((w['date'] for w in completed.values()), default=None) if all_done else None,
                debt=rows[-1]['debt'], cash=cash,
                missed=[w.name for i, w in enumerate(works) if deadlines[i] and deadlines[i] <= rows[-1]['date'] and (i not in completed or not completed[i]['on_time'])])
