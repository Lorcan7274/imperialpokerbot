import json, sys, glob
sys.path.insert(0,'/home/user/imperialpokerbot')
from tools.handstats import to_history, describe
from tools.pnl import clones_of
from pokerbot.model import classify
from pokerbot.cards import parse_card, evaluate
from pokerbot.preflop import percentile
from pokerbot.ranges import made
S='/tmp/claude-0/-home-user/226e6cb3-d110-550a-ae17-0779f3473502/scratchpad'
BL={1:3,2:4,3:5}
files = sys.argv[1:] or sorted(glob.glob(S+'/hands/saturday_r0*.json'))
tot={}
for f in files:
    d=json.load(open(f)); names=d['players']; n=len(names); me=d['seat']; ver=d['round']['version']
    clones=clones_of(d)
    for h in d['hands']:
        ev=classify(to_history(h),20,n=n)
        hole=[parse_card(c) for c in h['hole'][str(me)]]
        board=[parse_card(c) for c in h.get('board') or []]
        p=percentile(*hole)
        invested=0; tag=None
        clone_in=any(e.player in clones and e.act in('call','raise') for e in ev)
        for e in ev:
            if e.player!=me: continue
            if e.act in ('call','raise'):
                put=e.rec.amount
                if e.street==0 and e.rec.to>=1000 and p>0.15 and not clone_in: tag=tag or "preflop %s to %d with a weak hand (p=%.2f)"%(e.act,e.rec.to,p)
                if e.street>0 and len(board)>=BL[e.street]:
                    b=board[:BL[e.street]]; br=[c>>2 for c in b]
                    top=made(hole[0]>>2,hole[1]>>2,br,max(br)) or (evaluate(hole+b)>>20)>=2
                    if not top and put>=700 and not clone_in:
                        tag=tag or "%s %d on street %d without top pair"%(e.act,put,e.street)
        if tag:
            key=(tag.split(' ')[0]+' '+tag.split(' ')[1], ver)
            t=tot.setdefault(key,[0,0]); t[0]+=1; t[1]+=h['results'][me]
            print("%s v%s #%-4d %+5d %s | %s | board %s | shown %s\n      %s"%(d['round']['ref'][-4:],ver,h['n'],h['results'][me],"".join(h['hole'][str(me)]),tag," ".join(h['board']),{names[int(k)][:8]:"".join(v) for k,v in h['hole'].items() if k!=str(me)},describe(h,me)[:200]))
print({k:v for k,v in sorted(tot.items(), key=str)})
