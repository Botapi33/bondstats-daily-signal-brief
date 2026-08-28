#!/usr/bin/env python3
import json, urllib.request, pathlib, datetime as dt, math, shutil
ROOT=pathlib.Path(__file__).resolve().parents[1]; DATA=ROOT/'data'; ARCH=DATA/'archive'
URLS={
 'macro':'https://botapi33.github.io/bondstats-macro-data-watch/data/macro.json',
 'policy':'https://botapi33.github.io/bondstats-central-bank-watch/data/policy.json',
 'calendar':'https://botapi33.github.io/bondstats-market-calendar/data/events.json',
 'yields':'https://botapi33.github.io/bondstats-global-yields/global_yields.json'}

def fetch(url):
 req=urllib.request.Request(url,headers={'User-Agent':'BondStats-Daily-Signal-Brief/1.0'})
 with urllib.request.urlopen(req,timeout=25) as r: return json.load(r)
def iso(v):
 if not v:return None
 try:return dt.datetime.fromisoformat(v.replace('Z','+00:00'))
 except:return None
def num(v):
 try:return float(v)
 except:return None
def load_old():
 p=DATA/'latest.json'
 return json.load(open(p)) if p.exists() else None
def load_snapshot(name):
 p=DATA/'snapshots'/f'{name}.json'
 return json.load(open(p)) if p.exists() else None
def save_snapshot(name,d):
 p=DATA/'snapshots'; p.mkdir(exist_ok=True); json.dump(d,open(p/f'{name}.json','w'),indent=2,ensure_ascii=False)
def market_rows(y):
 out=[]
 for key,x in (y.get('countries') or {}).items():
  v=num(x.get('value')); prev=num(x.get('previousValue')); stale=x.get('stalenessDays',999)
  fresh=(str(x.get('frequency','')).lower()=='daily' and not x.get('isFallback') and isinstance(stale,(int,float)) and stale<=7)
  ch=(v-prev)*100 if fresh and v is not None and prev is not None else None
  out.append({'id':key,'label':x.get('label',key),'yield':v,'changeBp':round(ch,1) if ch is not None else None,'date':x.get('date'),'freshDaily':fresh,'source':x.get('source')})
 return out
def macro_changes(m):
 rows=[]
 for x in m.get('indicators',[]):
  a=num(x.get('value')); b=num(x.get('previous'))
  rows.append({'id':x.get('id'),'name':x.get('name'),'region':x.get('region'),'group':x.get('group'),'value':a,'previous':b,'unit':x.get('unit'),'transform':x.get('transform'),'period':x.get('period'),'direction':x.get('direction'),'relevance':x.get('marketRelevance'),'sourceName':x.get('sourceName'),'sourceUrl':x.get('sourceUrl')})
 return rows
def upcoming(c,now):
 ev=[]
 for x in c.get('events',[]):
  t=iso(x.get('dateTime') or x.get('datetime') or x.get('date'))
  if not t: continue
  if t.tzinfo is None:t=t.replace(tzinfo=dt.timezone.utc)
  if t>=now and t<=now+dt.timedelta(days=7):
   ev.append((t,x))
 ev.sort(key=lambda z:z[0]); out=[]
 for t,x in ev[:8]:
  out.append({'title':x.get('title') or x.get('name'),'dateTime':t.isoformat().replace('+00:00','Z'),'impact':x.get('impactLabel') or x.get('impact') or 'Scheduled','category':x.get('category'),'sourceName':x.get('sourceName'),'sourceUrl':x.get('sourceUrl')})
 return out
def next_policy(p,now):
 arr=[]
 for b in p.get('banks',[]):
  try:d=dt.datetime.fromisoformat(b['nextMeeting']).replace(tzinfo=dt.timezone.utc)
  except:continue
  if d>=now:arr.append((d,b))
 arr.sort(key=lambda z:z[0]);
 return [{'bank':b['name'],'date':d.date().isoformat(),'rate':b.get('displayRate'),'stance':b.get('stance'),'sourceUrl':b.get('scheduleUrl') or b.get('sourceUrl')} for d,b in arr[:4]]
def signal_text(markets,macro):
 fresh=[x for x in markets if x['changeBp'] is not None]
 fresh.sort(key=lambda x:abs(x['changeBp']),reverse=True)
 signals=[]
 for x in fresh[:3]:
  direction='rose' if x['changeBp']>0 else 'fell'
  signals.append({'kicker':'RATES','headline':f"{x['label']} yield {direction} {abs(x['changeBp']):.1f} bp",
   'body':'A fresh daily move in the sovereign yield feed. The brief reports the observed change without assigning a news-driven cause.', 'strength':min(100,round(abs(x['changeBp'])*5+35))})
 crit=[x for x in macro if x['relevance']=='Critical' and x['value'] is not None and x['previous'] is not None and x['value']!=x['previous']]
 for x in crit[:2]:
  verb='eased' if x['value']<x['previous'] else 'strengthened'
  signals.append({'kicker':x['group'].upper(),'headline':f"{x['region']} {x['name']} {verb}", 'body':f"Latest official observation: {x['value']:g}{x['unit']} versus {x['previous']:g}{x['unit']} previously ({x['period']}).",'strength':72,'sourceName':x.get('sourceName'),'sourceUrl':x.get('sourceUrl')})
 return signals[:5]
def dislocations(markets,macro):
 out=[]
 us=next((x for x in markets if x['id'].lower() in ('usa','us','united states')),None)
 inf=next((x for x in macro if x['id'] in ('US_CPI','US_CORE_CPI')),None)
 if us and us['changeBp'] is not None and inf and inf['value'] is not None and inf['previous'] is not None:
  if us['changeBp']<0 and inf['value']>inf['previous']:
   out.append({'pair':'YIELDS ↓  /  INFLATION ↑','title':'Rates and inflation are moving in opposite directions','body':'A fresh decline in the U.S. sovereign yield feed sits against a higher latest inflation reading. This is a detected divergence, not a claim about causality.'})
  if us['changeBp']>0 and inf['value']<inf['previous']:
   out.append({'pair':'YIELDS ↑  /  INFLATION ↓','title':'Rates rose despite softer latest inflation','body':'The latest inflation observation eased while the fresh sovereign yield move was higher. BondStats flags the mismatch for further analysis.'})
 return out

def main():
 now=dt.datetime.now(dt.timezone.utc); old=load_old(); src={}; health={}
 for k,u in URLS.items():
  try: src[k]=fetch(u); save_snapshot(k,src[k]); health[k]='ok'
  except Exception as e:
   src[k]=load_snapshot(k); health[k]='degraded' if src[k] else 'unavailable'
 if not src.get('macro') or not src.get('policy') or not src.get('calendar'):
  if old: print('Required source unavailable; retaining last-known-good brief.'); return
  raise SystemExit('Required source unavailable and no last-known-good brief exists.')
 markets=market_rows(src.get('yields') or {})
 macro=macro_changes(src['macro']); events=upcoming(src['calendar'],now); policy=next_policy(src['policy'],now)
 signals=signal_text(markets,macro); dis=dislocations(markets,macro)
 fresh=[x for x in markets if x['changeBp'] is not None]
 up=sum(x['changeBp']>0 for x in fresh); down=sum(x['changeBp']<0 for x in fresh)
 state='Mixed'
 if fresh and up>=max(2,down*2):state='Yields rising broadly'
 elif fresh and down>=max(2,up*2):state='Yields falling broadly'
 brief={
  'meta':{'product':'BondStats Daily Signal Brief','date':now.date().isoformat(),'generatedAt':now.isoformat().replace('+00:00','Z'),'version':'1.0.0','copyrightMethod':'Original deterministic analysis from factual/official and BondStats-owned data feeds; no third-party news articles or editorial text are ingested.','sourceHealth':health},
  'marketState':{'label':state,'freshDailyMarkets':len(fresh),'rising':up,'falling':down},
  'signals':signals,'dislocations':dis,'markets':fresh[:12],'macro':macro,'nextEvents':events,'nextPolicy':policy,
  'methodology':['No news articles are scraped, copied, summarized or rewritten.','Narrative text is generated deterministically from structured facts and BondStats data.','Causality is not inferred from coincident market moves.','Stale, fallback or non-daily yield observations are excluded from daily-change claims.','Official source links remain attached to macro, policy and calendar facts.']}
 DATA.mkdir(exist_ok=True); ARCH.mkdir(exist_ok=True)
 tmp=DATA/'latest.tmp'; json.dump(brief,open(tmp,'w'),indent=2,ensure_ascii=False); tmp.replace(DATA/'latest.json')
 ap=ARCH/f"{now.date().isoformat()}.json"
 if not ap.exists(): json.dump(brief,open(ap,'w'),indent=2,ensure_ascii=False)
 manifest=[]
 for p in sorted(ARCH.glob('*.json'),reverse=True):
  try:d=json.load(open(p)); manifest.append({'date':d['meta']['date'],'marketState':d['marketState']['label'],'signals':len(d.get('signals',[]))})
  except:pass
 json.dump({'updatedAt':now.isoformat().replace('+00:00','Z'),'days':manifest},open(DATA/'archive.json','w'),indent=2)
 print('Brief updated:',now.date(),health)
if __name__=='__main__':main()
