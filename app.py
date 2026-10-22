from dataclasses import asdict
from datetime import date, datetime
from zoneinfo import ZoneInfo
import json

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from model import Settings, Work, Scenario, add_months, month_date, simulate
from plan_io import load_plan


st.set_page_config(page_title="KÜ · Remondiplaan", page_icon="🏡", layout="wide")
COLORS = ['#087F72', '#5277CB', '#E7A33E', '#9A67BA', '#CE6472', '#4C9FB0']
MONTHS = ['Jaanuar', 'Veebruar', 'Märts', 'Aprill', 'Mai', 'Juuni', 'Juuli', 'August', 'September', 'Oktoober', 'November', 'Detsember']
MODES = {'none': 'Ilma laenuta', 'deadline': 'Puudujääk töö tähtajaks', 'fixed': 'Kindel summa kindlal kuul'}


def euro(value):
    return f'{value:,.0f} €'.replace(',', ' ')


def month(value):
    return value.strftime('%m.%Y') if value else '—'


def defaults():
    start = datetime.now(ZoneInfo('Europe/Tallinn')).date().replace(day=1)
    return dict(settings=asdict(Settings(start=start)), works=[
        dict(name='Torustiku vahetus', cost=45000., annual_loss=5000., deadline=add_months(start, 24)),
        dict(name='Katuse remont', cost=80000., annual_loss=1500., deadline=None),
        dict(name='Fassaadi korrastamine', cost=120000., annual_loss=0., deadline=None)], scenarios=[
        asdict(Scenario('1 € · 12 kuud')),
        asdict(Scenario('1 € · 8 kuud', months=list(range(3, 11)))),
        asdict(Scenario('1 € · 6 suvekuud', months=list(range(5, 11)))),
        asdict(Scenario('1 € · 12 kuud + laen', loan_mode='deadline'))])


if 'plan' not in st.session_state:
    st.session_state.plan = defaults()
    st.session_state.revision = 0
plan = st.session_state.plan
rev = st.session_state.revision


def key(name):
    return f'{rev}_{name}'


st.markdown('<style>.block-container{padding-top:2rem} div[data-testid="stMetric"]{background:white;border:1px solid #E0E7EE;border-radius:12px;padding:16px} h1{letter-spacing:-1.5px} div[data-testid="stSidebar"]{border-right:1px solid #E0E7EE}</style>', unsafe_allow_html=True)
st.caption('KORTERIÜHISTU FINANTSPLANEERIJA')
st.title('Hea remondiplaan algab arvudest.')
st.write('Võrdle kogumist, tööde järjekorda ja laenu mõju ühistu vabale rahale.')

with st.sidebar:
    st.header('Ühistu lähteandmed')
    s = plan['settings']
    area = st.number_input('Arvestuslik pindala, m²', min_value=1., value=float(s['area']), step=100., key=key('area'))
    initial = st.number_input('Remondifondi algsaldo, €', min_value=0., value=float(s['initial_cash']), step=1000., key=key('initial'))
    deposit_rate = st.number_input('Vaba raha hoiuseintress, % aastas', min_value=0., max_value=100., value=float(s.get('deposit_rate', Settings().deposit_rate) * 100), step=.1, key=key('deposit_rate'), help='Intress teenitakse kuu alguse positiivselt saldolt: aastamäär / 12. Lisandub iga kuu fondi ning on kohe kasutatav. 0% lülitab hoiustamise välja.') / 100
    start = st.date_input('Arvutuse alguskuu', value=s['start'], key=key('start')).replace(day=1)
    years = st.slider('Võrdlusperiood, aastat', 1, 50, int(s['years']), key=key('years'))
    construction = st.number_input('Ehitushinna muutus, % aastas', min_value=-20., max_value=50., value=float(s['construction'] * 100), step=.5, key=key('construction'), help='Tööde nominaalne hinnamuutus. Sisaldab juba inflatsiooni.') / 100
    inflation = st.number_input('Inflatsioon, % aastas', min_value=-20., max_value=50., value=float(s['inflation'] * 100), step=.5, key=key('inflation'), help='Suurendab tegemata tööde avarii- ja hoolduskulusid. Kasutatakse ka tänasesse rahasse teisendamisel.') / 100
    st.caption('Ehitushinna indeks sisaldab inflatsiooni. Tööde hinda korrigeeritakse ainult ehitushinna muutusega.')
    st.divider()
    with st.expander('Ava salvestatud plaan'):
        uploaded = st.file_uploader('Plaani JSON-fail', type=['json'])
        if st.button('Laadi plaan', disabled=uploaded is None):
            try:
                st.session_state.plan = load_plan(json.loads(uploaded.getvalue()))
                st.session_state.revision += 1
                st.rerun()
            except (ValueError, TypeError, KeyError, AttributeError) as exc:
                st.error(f'Plaani ei saanud avada: {exc}')
settings = Settings(area=area, initial_cash=initial, inflation=inflation, construction=construction, years=years, start=start, deposit_rate=deposit_rate)

st.subheader('1. Tööd ja prioriteedid')
st.caption('Muuda järjekorranumbrit, lisa ridu või kustuta valitud read. Järgmine töö algab alles pärast eelmist. Tähtaeg käivitab laenu ainult tähtajapõhises laenustsenaariumis.')
work_df = pd.DataFrame([dict(jrk=i+1, **w) for i, w in enumerate(plan['works'])])
# Millisecond precision supports all calendar years accepted by the date editor.
# Nanosecond timestamps overflow on e.g. year 1000 during an in-progress edit.
work_df['deadline'] = pd.array(work_df['deadline'], dtype='datetime64[ms]')
edited = st.data_editor(work_df, hide_index=True, num_rows='dynamic', width='stretch', key=key('works'), column_config={
    'jrk': st.column_config.NumberColumn('Järjekord', min_value=1, step=1, required=True, width='small'),
    'name': st.column_config.TextColumn('Töö', required=True, width='large'),
    'cost': st.column_config.NumberColumn('Hind täna, €', min_value=0., step=1000., required=True, format='%.0f €'),
    'annual_loss': st.column_config.NumberColumn('Kulu kuni töö tegemiseni, €/a', min_value=0., step=100., format='%.0f €', help='Aastane avarii- või hoolduskulu tänases hinnas. Lõpeb töö tegemisele järgnevast kuust.'),
    'deadline': st.column_config.DateColumn('Soovitud tähtaeg', format='MM.YYYY', help='Valikuline. Tööd tehakse võimalusel varem; laen katab puuduva raha hiljemalt sel kuul.')})

st.subheader('2. Kogumise ja laenu stsenaariumid')
count = st.number_input('Võrdluses stsenaariume', min_value=1, max_value=6, value=len(plan['scenarios']), step=1, key=key('count'))
scenarios = []
for i in range(count):
    base = plan['scenarios'][i] if i < len(plan['scenarios']) else asdict(Scenario(f'Stsenaarium {i+1}'))
    with st.expander(f"{i+1:02d} · {base['name']}", expanded=i == 0):
        a, b, c = st.columns([2, 1, 2])
        name = a.text_input('Nimi', base['name'], key=key(f'name{i}'))
        rate = b.number_input('Kogumine, €/m² kuus', min_value=0., value=float(base['rate']), step=.1, key=key(f'rate{i}'))
        index = c.checkbox('Kogumismäär kasvab inflatsiooniga', value=base['index_contributions'], key=key(f'index{i}'))
        months = st.multiselect('Kuud, millal remondifondi kogutakse', options=list(range(1, 13)), default=base['months'], format_func=lambda m: MONTHS[m-1], key=key(f'months{i}'))
        st.caption(f'Esimese aasta tasemel {euro(rate * area)} kogumiskuu kohta · {euro(rate * area * len(months))} täisaastas.')
        mode = st.selectbox('Laenu kasutamine', list(MODES), index=list(MODES).index(base['loan_mode']), format_func=MODES.get, key=key(f'mode{i}'))
        sc = Scenario(name=name, rate=rate, months=months, index_contributions=index, loan_mode=mode)
        if mode != 'none':
            a, b, c, d = st.columns(4)
            sc.interest = a.number_input('Intress kokku, % aastas', min_value=0., max_value=30., value=float(base['interest']*100), step=.25, key=key(f'int{i}'), help='Näiteks baasintress + panga marginaal. Mudelis püsib intress fikseeritud.') / 100
            sc.term_years = b.number_input('Laenu pikkus, aastat', min_value=1, max_value=40, value=int(base['term_years']), key=key(f'term{i}'))
            sc.fee = c.number_input('Lepingutasu, % laenust', min_value=0., max_value=20., value=float(base['fee']*100), step=.1, key=key(f'fee{i}')) / 100
            sc.loan_limit = d.number_input('Laenude kogulimiit, €', min_value=0., value=float(base['loan_limit']), step=10000., key=key(f'limit{i}'))
            sc.extra_repayment = st.checkbox('Laenumaksed kogutakse omanikelt remondifondile lisaks', value=base['extra_repayment'], key=key(f'extra{i}'), help='Vaikimisi vähendavad põhiosa ja intress remondifondi vaba raha. Selle valiku korral lisandub eraldi igakuine makse kõigil kuudel.')
            if mode == 'fixed':
                a, b = st.columns(2)
                sc.loan_date = a.date_input('Laenu väljamakse kuu', value=base['loan_date'] or add_months(start, 12), key=key(f'loandate{i}')).replace(day=1)
                sc.loan_amount = b.number_input('Laenu põhisumma, €', min_value=0., value=float(base['loan_amount']), step=5000., key=key(f'amount{i}'))
            else:
                st.caption('Laen võetakse töö tähtajal ainult puuduvas ulatuses, koos lepingutasuga. Varasemad tööd rahastatakse vajadusel sama tähtaja jaoks. Limiit piirab kõigi väljamaksete summat.')
        scenarios.append(sc)

try:
    if edited['jrk'].isna().any() or edited['jrk'].duplicated().any():
        raise ValueError('Anna igale tööle erinev järjekorranumber.')
    works = [Work(name=row['name'], cost=float(row['cost']), annual_loss=0. if pd.isna(row['annual_loss']) else float(row['annual_loss']), deadline=None if pd.isna(row['deadline']) else month_date(row['deadline'])) for _, row in edited.sort_values('jrk', kind='stable').iterrows()]
    if any(not c.name.strip() for c in scenarios) or len({c.name.strip() for c in scenarios}) != len(scenarios):
        raise ValueError('Anna stsenaariumidele erinevad, mittetühjad nimed.')
    results = [simulate(settings, works, c) for c in scenarios]
except (ValueError, TypeError, KeyError) as exc:
    st.error(f'Kontrolli sisendeid: {exc}')
    st.stop()

payload = dict(version=1, settings=asdict(settings), works=[asdict(w) for w in works], scenarios=[asdict(c) for c in scenarios])
st.sidebar.download_button('Salvesta plaan JSON-failina', json.dumps(payload, ensure_ascii=False, indent=2, default=str), 'remondiplaan.json', 'application/json', width='stretch')
frames = [pd.DataFrame(r['rows']).assign(scenario=c.name) for c, r in zip(scenarios, results)]
all_months = pd.concat(frames, ignore_index=True)
all_months['date'] = pd.to_datetime(all_months['date'])
color_map = {c.name: COLORS[i] for i, c in enumerate(scenarios)}

st.divider()
st.subheader('3. Plaanide võrdlus')
a, b, c = st.columns(3)
a.metric('Tööde maksumus täna', euro(sum(w.cost for w in works)))
b.metric('Tegemata tööde algne aastakulu', euro(sum(w.annual_loss for w in works)))
c.metric('Võrdluse lõpp', month(add_months(start, years * 12 - 1)))

summary = []
for sc, r in zip(scenarios, results):
    summary.append({'Stsenaarium': sc.name, 'Töid valmis': f"{len(r['completed'])}/{len(works)}", 'Kõik tööd valmis': month(r['finish']), 'Rahavoog': 'Piisav' if r['feasible'] else 'Puudujääk', 'Kulud + tulevane laenuintress, €': round(r['total_cost']), 'Omanikelt kogutud, €': round(r['totals']['contributions'] + r['totals']['extra']), 'Vaba raha lõpus, €': round(r['cash']), 'Laenujääk lõpus, €': round(r['debt'])})
for row, r in zip(summary, results):
    row['Hoiusetulu, €'] = round(r['totals']['deposit_income'])
    row['Kulud miinus hoiusetulu, €'] = round(r['net_cost'])
st.dataframe(pd.DataFrame(summary), hide_index=True, width='stretch')
st.caption('Kulu = tehtud tööd + avarii/hoolduskulud + lepingutasud + intressid, sh võetud laenude ülejäänud intress kuni tasumiseni. Tegemata töid sellesse summasse ei lisata. Võrdle ka valmis tööde arvu ja laenujääki.')
st.caption('Hoiusetulu suurendab vaba raha ja on kuludest eraldi. „Kulud miinus hoiusetulu” lahutab kogukulust võrdlusperioodil teenitud hoiuseintressi; perioodijärgset hoiusetulu ei prognoosita.')
for sc, r in zip(scenarios, results):
    if not r['feasible']:
        first = next(x['date'] for x in r['rows'] if x['cash'] < -.01)
        st.warning(f"{sc.name}: raha jääb puudu alates {month(first)}. Suurim katmata puudujääk on {euro(-r['minimum_cash'])}. Negatiivne saldo tähistab lisarahastuse vajadust; selle stsenaariumi tööde ajakava eeldab puudujäägi katmist.")
    if r['missed']:
        st.warning(f"{sc.name}: tähtajaks tegemata või hilinenud tööd: {', '.join(r['missed'])}.")
    if sc.loan_mode == 'deadline' and not any(w.deadline for w in works):
        st.info(f'{sc.name}: tähtajapõhise laenu jaoks määra vähemalt ühele tööle tähtaeg.')


def line_chart(data, y, title, label):
    fig = px.line(data, x='date', y=y, color='scenario', color_discrete_map=color_map, labels={'date': 'Kuu', y: label, 'scenario': 'Stsenaarium'})
    fig.update_layout(title=title, height=390, margin=dict(l=10, r=15, t=60, b=20), legend=dict(orientation='h', y=-.2), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='white', hovermode='x unified')
    fig.update_yaxes(tickformat=',.0f', gridcolor='#EBEFF4', zerolinecolor='#9DAABA')
    st.plotly_chart(fig, width='stretch')


tab1, tab2, tab3, tab4 = st.tabs(['Raha ja ajakava', 'Kulud ja laenud', 'Stsenaariumi detailid', 'Arvutuse põhimõtted'])
with tab1:
    line_chart(all_months, 'cash', 'Kui palju vaba raha jääb remondifondi?', 'Vaba raha, €')
    st.caption('Saldo pärast selle kuu kogumist, laenumakseid, avariikulusid ja tööde eest tasumist. Laenumaksed toimuvad ka kuudel, mil remondifondi ei koguta.')
    fig = go.Figure()
    labels = [f'{i+1}. {w.name}' for i, w in enumerate(works)]
    for j, (sc, r) in enumerate(zip(scenarios, results)):
        done = list(r['completed'].items())
        fig.add_trace(go.Scatter(x=[v['date'] for i, v in done], y=[labels[i] for i, v in done], name=sc.name, mode='markers', marker=dict(size=13, color=COLORS[j], symbol=['circle', 'diamond', 'square', 'triangle-up', 'cross', 'star'][j]), customdata=[[euro(v['cost'])] for i, v in done], hovertemplate='%{y}<br>%{x|%m.%Y}<br>%{customdata[0]}<extra>%{fullData.name}</extra>'))
    fig.update_layout(title='Millal saab tööd valmis?', height=max(330, len(works)*65+130), xaxis=dict(title='Valmimise kuu', type='date', range=[pd.Timestamp(start), pd.Timestamp(add_months(start, years*12))]), yaxis=dict(autorange='reversed', categoryorder='array', categoryarray=labels), legend=dict(orientation='h', y=-.25), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='white')
    st.plotly_chart(fig, width='stretch')
    timing = [{'Töö': labels[i], **{sc.name: month(r['completed'][i]['date']) if i in r['completed'] else 'Perioodis tegemata' for sc, r in zip(scenarios, results)}} for i in range(len(works))]
    st.dataframe(pd.DataFrame(timing), hide_index=True, width='stretch')
with tab2:
    costs = []
    for sc, r in zip(scenarios, results):
        for component, value in [('Tehtud tööd', r['totals']['repairs']), ('Avarii/hooldus', r['totals']['losses']), ('Lepingutasud', r['totals']['fees']), ('Makstud intress', r['totals']['interest']), ('Tulevane laenuintress', r['future_interest'])]:
            costs.append(dict(Stsenaarium=sc.name, Kululiik=component, Eurot=value))
    fig = px.bar(pd.DataFrame(costs), x='Stsenaarium', y='Eurot', color='Kululiik', color_discrete_sequence=COLORS, title='Millest kogukulu koosneb?')
    fig.update_layout(legend=dict(orientation='h', y=-.3), paper_bgcolor='rgba(0,0,0,0)', height=440)
    st.plotly_chart(fig, width='stretch')
    line_chart(all_months, 'debt', 'Laenujääk läbi aja', 'Laenujääk, €')
    line_chart(all_months, 'cumulative_deposit_income', 'Vabalt rahalt teenitud hoiuseintress', 'Hoiusetulu kokku, €')
    line_chart(all_months, 'debt_service', 'Igakuine laenumakse: põhiosa + intress', 'Laenumakse, €/kuu')
    line_chart(all_months, 'household_payment', 'Omanike maksed kokku', 'Omanikelt kogutav, €/kuu')
with tab3:
    selected = st.selectbox('Vaata lähemalt', [c.name for c in scenarios])
    idx = next(i for i, c in enumerate(scenarios) if c.name == selected)
    r, sc = results[idx], scenarios[idx]
    a, b, c, d = st.columns(4)
    a.metric('Laenu võetud kokku', euro(r['totals']['borrowed']))
    b.metric('Intress kokku laenude lõpuni', euro(r['totals']['interest'] + r['future_interest']))
    c.metric('Suurim kuine laenumakse', euro(max(x['debt_service'] for x in r['rows'])))
    d.metric('Perioodi kulud tänases rahas', euro(r['real_cost']))
    a, b = st.columns(2)
    a.metric('Hoiusetulu perioodil', euro(r['totals']['deposit_income']))
    b.metric('Kulud miinus hoiusetulu tänases rahas', euro(r['real_net_cost']))
    st.caption('Tänases rahas on ainult võrdlusperioodil tehtud kulutused; perioodijärgseid intresse sellesse näitajasse ei lisata.')
    if r['loans']:
        st.write('Laenu väljamaksed ja tagasimaksmine')
        loan_rows = [{'Kuu': month(l['date']), 'Põhjus': l['reason'], 'Põhisumma, €': round(l['amount'], 2), 'Lepingutasu, €': round(l['fee'], 2), 'Kuumakse, €': round(l['payment'], 2), 'Kuumakse, €/m²': round(l['payment']/area, 3), 'Viimane makse': month(l['maturity'])} for l in r['loans']]
        st.dataframe(pd.DataFrame(loan_rows), hide_index=True, width='stretch')
    else:
        st.info('Selles stsenaariumis pole võrdlusperioodil laenu võetud.')
    df = frames[idx].copy()
    df['Aasta'] = pd.to_datetime(df['date']).dt.year
    annual = df.groupby('Aasta').agg(Kogutud=('contributions', 'sum'), Lisamaksed=('extra', 'sum'), Tööd=('repairs', 'sum'), Avariikulud=('losses', 'sum'), Laenumaksed=('debt_service', 'sum'), Intress=('interest', 'sum'), Laenu_võetud=('borrowed', 'sum'), Lepingutasud=('fees', 'sum'), Vaba_raha=('cash', 'last'), Laenujääk=('debt', 'last')).round(2)
    st.write('Rahavoog aastate kaupa, €')
    annual.insert(1, 'Hoiusetulu', df.groupby('Aasta')['deposit_income'].sum().round(2))
    st.dataframe(annual, width='stretch')
    st.caption('Esimene ja viimane kalendriaasta võivad olla osalised. Intress sisaldub laenumaksetes.')
    csv_names = {'date':'Kuu', 'scenario':'Stsenaarium', 'cash':'Vaba raha', 'debt':'Laenujääk', 'net':'Raha miinus laenujääk', 'contributions':'Remondifondi kogutud', 'extra':'Laenu lisamaksed', 'losses':'Avariikulud', 'repairs':'Tööd', 'borrowed':'Laenu võetud', 'fees':'Lepingutasud', 'interest':'Intress', 'principal':'Põhiosa', 'debt_service':'Laenumakse', 'household_payment':'Omanike maksed', 'completed':'Töid valmis', 'paid_cost':'Kulud kumulatiivselt'}
    csv_names.update(deposit_income='Hoiusetulu', cumulative_deposit_income='Hoiusetulu kumulatiivselt')
    st.download_button('Laadi kõigi stsenaariumite kuupõhine CSV', all_months.rename(columns=csv_names).to_csv(index=False, sep=';', decimal=',').encode('utf-8-sig'), 'remondiplaan_rahavood.csv', 'text/csv')
with tab4:
    st.markdown('''
**Ajaarvestus.** Arvutus käib kuude kaupa. Esimese kuu hinnad on tänastes hindades.
Järgmistes kuudes kasutatakse aastakasvu astmes `möödunud kuud / 12`. Kuupäeva puhul arvestatakse kuud.

**Hinnad.** Töö hind = tänane hind × `(1 + ehitushinna muutus) ^ (kuud / 12)`.
Ehitushinna indeks sisaldab inflatsiooni. Inflatsioon kasvatab tegemata tööde aastakulu ning soovi korral kogumismäära.
Tänases rahas kulu leitakse jagades kuine kulu sama kuu inflatsiooniteguriga.

**Hoiustamine.** Kogu kuu alguse positiivne vaba raha teenib muudetava määraga hoiuseintressi (vaikimisi 2,7% aastas).
Kuine tulu = `max(kuu algsaldo, 0) × aastamäär / 12`. Intress lisandub fondi enne kuu lõpu makseid.
Sama kuu laekumised ja laenu väljamaksed hakkavad intressi teenima järgmisel kuul, kui need jäävad vabaks rahaks.
Negatiivne saldo hoiuseintressi ei teeni. Eeldatakse vabalt kasutatavat hoiust ilma väljavõtupiirangute, tasude või maksudeta.
0% lülitab hoiustamise välja. Vanas JSON-plaanis puuduva määra asemel kasutatakse 2,7%; salvestamisel lisatakse määr faili.

**Kuu rahavoog.** Algsaldole lisanduvad hoiuseintress ja remondifondi kogumine, seejärel tasutakse olemasolevate laenude põhiosa ja intress ning tegemata tööde aastakulust 1/12.
Vajadusel võetakse laen ja makstakse lepingutasu. Seejärel tehakse järjekorras kõik tööd, milleks raha jätkub.
Avariikulud lõpevad töö valmimisele järgneval kuul. Tööd loetakse tasutuks ja valminuks samal kuul; ehituse kestust ei modelleerita.

**Laen.** Fikseeritud intressiga annuiteetlaen; kuuintress = aastaintress / 12. Esimene makse on väljamaksele järgneval kuul.
Iga väljamakse saab määratud pikkusega oma maksegraafiku. Kõigi aktiivsete laenude maksed liidetakse.
Põhiosa ja intress vähendavad vaikimisi vaba raha kõigil 12 kuul. Eraldi kogumise valik lisab selleks omanikele täiendava kuumakse.
Laenu ei maksta ennetähtaegselt tagasi ka siis, kui fondi jääb üle raha.

**Tähtajad ja limiit.** Tähtajalaen katab vaid tööks puuduva raha koos lepingutasuga, säilitades tööde järjekorra.
Hilisema töö tähtaeg kehtib vajadusel ka selle eelnevatele töödele. Laenulimiit on kõigi väljamaksete summa, mitte hetke laenujääk.
Kindla laenu korral peetakse lepingutasu väljamaksest kinni. Tähtajalaen ei otsi matemaatiliselt odavaimat laenamise hetke.

**Puudujääk.** Negatiivne saldo näitab rahastamata kohustusi, mitte automaatselt lubatud arvelduskrediiti.
Puudujäägiga plaan ei ole praeguste eeldustega rahastatav; graafikut tuleb lugeda koos hoiatusega.

**Kogukulu.** Tööde maksumus, tegemata tööde jooksvad kulud, lepingutasud ja intress.
Laenu põhiosa ei liideta kulusse teist korda. Tulevane intress arvutatakse juba võetud laenude lõpuni;
perioodijärgseid avariikulusid ega veel tegemata töid ei prognoosita kogukulu sisse.
Seetõttu pole tegemata töödega stsenaariumi madalam kogukulu võrreldav lõpetatud plaaniga.

**Eeldused.** Kõik hinnad sisesta koos käibemaksuga. Toetusi, pangapoolset krediidiotsust ega makseviivitusi ei modelleerita.
Algandmed on muudetavad näited, mitte ühistu hinnapakkumised või panga laenupakkumine.
''')

