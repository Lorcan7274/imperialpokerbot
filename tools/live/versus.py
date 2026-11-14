import json,glob,sys
from collections import defaultdict
sys.path.insert(0,'/home/user/imperialpokerbot')
from tools.handstats import to_history
S='/tmp/claude-0/-home-user/226e6cb3-d110-550a-ae17-0779f3473502/scratchpad'
who=sys.argv[1]; show=len(sys.argv)>2
tot=defaultdict(lambda:[0,0.0]); rows=[]
for f in sorted(glob.glob(S+'/hands/saturday_r0*.json')):
    d=json.load(open(f)); names=d['players']; me=d['seat']; rn=f.split('_r')[-1][:3]
    if who not in names: continue
    wb=names.index(who)
    for h in d['hands']:
        hist=to_history(h); mynet=h['results'][me]
        pre=[r for r in hist if r.street==0 and r.kind not in('sb','bb')]
        post=[r for r in hist if r.street>0]
        folded=set(r.player for r in pre if r.kind=='fold')
        if not post or me in folded or wb in folded: continue
        flat=[]; 
        for st in (1,2,3):
            lastagg=None
            for r in [x for x in post if x.street==st]:
                nm=lambda p: 'ME' if p==me else 'V' if p==wb else 'OT'
                if r.kind=='raise':
                    flat.append(nm(r.player)+' bets' if lastagg is None else nm(r.player)+' raises '+nm(lastagg)); lastagg=r.player
                elif r.kind in('fold','call') and r.player in (me,wb):
                    flat.append(nm(r.player)+(' folds' if r.kind=='fold' else ' calls'))
        def after(tag,prefix):
            i=flat.index(tag); nxt=[x for x in flat[i+1:] if x.startswith(prefix)]
            return nxt[0].split(' ')[1] if nxt else '?'
        if 'V raises ME' in flat: tag='we bet, they raise -> we '+after('V raises ME','ME')
        elif 'ME raises V' in flat: tag='they bet, we raise -> they '+after('ME raises V','V')
        elif 'V bets' in flat: tag='they bet first -> we '+after('V bets','ME')
        elif 'ME bets' in flat: tag='we bet first -> they '+after('ME bets','V')
        else: tag='checked down / other'
        tot[tag][0]+=1; tot[tag][1]+=mynet; rows.append((rn,h,tag,mynet,me,wb,names))
print(who)
for k in sorted(tot):
    n,x=tot[k]; print("   %-40s n=%4d  our net %+7.0f chips (%+6.1f bb per hand)"%(k,n,x,x/20/max(1,n)))
if show:
    for rn,h,tag,mynet,me,wb,names in sorted(rows,key=lambda r:r[3])[:int(sys.argv[2])]:
        hist=to_history(h); out=[]; st=None; pot=0; bets={}
        for r in hist:
            if r.street!=st: st=r.street; out.append('|'+'PFTR'[st]+' pot%d:'%pot); bets={}
            if r.kind in('sb','bb'): pot+=r.to; bets[r.player]=r.to; continue
            nm='ME' if r.player==me else 'V' if r.player==wb else 'o%d'%r.player
            if r.kind in('call','raise'): pot+=r.to-bets.get(r.player,0); bets[r.player]=r.to
            if r.player in(me,wb) or (st>0 and r.kind!='fold'): out.append(nm+':'+{'raise':'r','call':'c','check':'x','fold':'f'}[r.kind]+(str(r.to) if r.kind in('raise','call') else ''))
        sd=''.join(h['hole'].get(str(wb),[])) if str(wb) in (h.get('showdown') or {}) else '-'
        print("r%s #%-4d %s board %-14s V %-5s %+6d %s"%(rn,h['n'],''.join(h['hole'][str(me)]),''.join(h.get('board') or []),sd,mynet,' '.join(out)[:200]))
