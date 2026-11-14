import json,glob,sys
from collections import defaultdict
sys.path.insert(0,'/home/user/imperialpokerbot')
sys.path.insert(0,'/tmp/claude-0/-home-user/226e6cb3-d110-550a-ae17-0779f3473502/scratchpad/live')
from fair import fair_result
from tools.handstats import to_history
from tools.pnl import clones_of
from pokerbot.model import classify
from pokerbot.cards import parse_card, evaluate
from pokerbot.ranges import made
S='/tmp/claude-0/-home-user/226e6cb3-d110-550a-ae17-0779f3473502/scratchpad'
BL={1:3,2:4,3:5}
files=sys.argv[1:] or sorted(glob.glob(S+'/hands/saturday_r0*.json'))[-4:]
for f in files:
    d=json.load(open(f)); names=d['players']; n=len(names); me=d['seat']; clones=clones_of(d)
    a=defaultdict(float)
    for h in d['hands']:
        ev=classify(to_history(h),20,n=n)
        if any(e.player in clones and e.act in('call','raise') for e in ev): continue
        hole=[parse_card(c) for c in h['hole'][str(me)]]; board=[parse_card(c) for c in h.get('board') or []]
        x=None
        for i,e in enumerate(ev):
            if e.player==me and e.street>0 and len(board)>=BL[e.street]:
                b=board[:BL[e.street]]; br=[c>>2 for c in b]
                strong=made(hole[0]>>2,hole[1]>>2,br,max(br)) or (evaluate(hole+b)>>20)>=2
                if e.act=='raise' and e.sit[:8]=='p_vs_bet':
                    k='raise_value' if strong else 'raise_bluff'
                    nxt=[y.act for y in ev[i+1:] if y.player!=me and y.street==e.street][:1]
                    if x is None: x=fair_result(h,me)[0]
                    a[k+'_n']+=1; a[k+'_fold']+= nxt==['fold']; a[k+'_net']+=x
                    break
                if e.street==3 and e.act in('call','fold') :
                    if x is None: x=fair_result(h,me)[0]
                    k='river_'+e.act
                    a[k+'_n']+=1; a[k+'_net']+=x; a[k+'_won']+= h['results'][me]>0
    print("%s v%-2s: raises over a bet: bluff %2d (folded %2d, net %+6.0f), value %2d (folded %2d, net %+6.0f) | river calls %2d (won %2d, net %+6.0f), river folds %2d"%(
        d['round']['ref'][-4:],d['round']['version'],a['raise_bluff_n'],a['raise_bluff_fold'],a['raise_bluff_net'],a['raise_value_n'],a['raise_value_fold'],a['raise_value_net'],a['river_call_n'],a['river_call_won'],a['river_call_net'],a['river_fold_n']))
