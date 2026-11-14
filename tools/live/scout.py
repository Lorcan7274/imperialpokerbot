import json,glob,os,sys
from collections import defaultdict, Counter
sys.path.insert(0,'/home/user/imperialpokerbot')
from tools.handstats import to_history
from pokerbot.model import classify, EDGES
from pokerbot.cards import parse_card, evaluate
from pokerbot.preflop import percentile, class_name
from pokerbot.ranges import made
S='/tmp/claude-0/-home-user/226e6cb3-d110-550a-ae17-0779f3473502/scratchpad'
who=sys.argv[1]
BL={1:3,2:4,3:5}
c=Counter(); sizes=defaultdict(Counter); shown=defaultdict(list); post=Counter(); sd=defaultdict(lambda:[0,0])
rounds=0
for f in sorted(glob.glob(S+'/hands/saturday_r0*.json')):
    d=json.load(open(f)); names=d['players']; n=len(names)
    if who not in names: continue
    rounds+=1; v=names.index(who)
    for h in d['hands']:
        ev=classify(to_history(h),20,n=n)
        hole=h.get('hole') or {}; s=h.get('showdown') or {}
        cards=[parse_card(x) for x in hole[str(v)]] if str(v) in hole and str(v) in s else None
        board=[parse_card(x) for x in h.get('board') or []]
        level=20
        for e in ev:
            if e.street==0:
                if e.player==v:
                    k=e.sit.split(':')[0]
                    c[(k,e.act)]+=1; c[(k,'n')]+=1
                    if e.act=='raise':
                        sizes[k]['allin' if e.rec.to>=2000 else round(e.rec.to/level,1) if k!='unopened' else e.rec.to]+=1
                        if cards: shown[(k,'allin' if e.rec.to>=2000 else 'raise')].append(class_name(*cards))
                    elif e.act=='call' and cards and e.rec.to>=400: shown[(k,'call>=400')].append(class_name(*cards))
                if e.act=='raise': level=e.rec.to
            elif e.player==v:
                k=e.sit[:8] if e.sit[:8]=='p_no_bet' else e.sit.split(':')[0]
                post[(e.street,k,e.act)]+=1; post[(e.street,k,'n')]+=1
                if e.act=='raise' and cards and len(board)>=BL[e.street]:
                    b=board[:BL[e.street]]; br=[x>>2 for x in b]
                    strong=made(cards[0]>>2,cards[1]>>2,br,max(br)) or (evaluate(cards+b)>>20)>=2
                    key=(e.street, 'bet' if k=='p_no_bet' else 'raise', 'big' if e.frac>=0.58 or k!='p_no_bet' else 'small')
                    sd[key][0]+=1; sd[key][1]+=strong
print(who, "rounds", rounds)
for k in ('unopened','vs_raise','vs_3bet','re_raised'):
    nn=c[(k,'n')]
    if nn: print("  preflop %-9s n=%5d: fold %2.0f%% call %2.0f%% raise %2.0f%% | sizes %s"%(k,nn,100*c[(k,'fold')]/nn,100*c[(k,'call')]/nn,100*c[(k,'raise')]/nn,dict(sizes[k].most_common(5))))
for k,v2 in shown.items(): print("  shown %-22s n=%3d: %s"%(k,len(v2)," ".join(sorted(v2))[:150]))
for st in (1,2,3):
    for k in ('p_no_bet','p_vs_bet','p_vs_raise'):
        nn=post[(st,k,'n')]
        if nn>=10: print("  street %d %-10s n=%4d: %s"%(st,k,nn," ".join("%s %2.0f%%"%(a,100*post[(st,k,a)]/nn) for a in ('fold','check','call','raise') if post[(st,k,a)])))
print("  strong (top pair+) at showdown when betting/raising:", {str(k):"%d/%d"%(v2[1],v2[0]) for k,v2 in sorted(sd.items())})
