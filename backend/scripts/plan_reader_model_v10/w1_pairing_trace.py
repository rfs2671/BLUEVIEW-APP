# w1_pairing_trace.py: for every window row (both tracks) look on its source page for the tag text nearest to the drawn window symbol and compare the symbol width with the A-400 type width.
import fitz,csv,re,json,collections as C
P='C:/Users/asddd/boyland-pdfs/'; V9='C:/Users/asddd/bv-worktrees/model_export_v09b/'
docs={};out=[]
for trk,f in [('filed','elements_filed.csv'),('post_co','elements_postco.csv')]:
    for r in csv.DictReader(open(V9+f,encoding='utf8')):
        if r['class']!='window': continue
        fn=r['source_file']; 
        if fn not in docs: docs[fn]=fitz.open(P+fn)
        pg=docs[fn][int(r['page'])-1]
        x0,y0,x1,y1=map(float,r['raw_bbox_pt'].split(';')); cx,cy=(x0+x1)/2,(y0+y1)/2
        wpt=max(x1-x0,y1-y0); sym_in=wpt/18*12
        # text spans that look like W<digit> (any rotation): find words
        words=[w for w in pg.get_text('words') if re.fullmatch(r'W-?\s?\d',w[4]) ]
        best=None
        for w in words:
            wx,wy=(w[0]+w[2])/2,(w[1]+w[3])/2; d=((wx-cx)**2+(wy-cy)**2)**.5
            if best is None or d<best[0]: best=(d,w[4],wx,wy)
        out.append(dict(track=trk,id=r['id'],level=r['level'],sheet=r['sheet'],page=r['page'],tag=r['tag'],sched_in=r['opening_width_in'],symbol_in=round(sym_in,1),near_tag=best and best[1],near_dist_pt=best and round(best[0],1),symbol_center=(round(cx,1),round(cy,1))))
json.dump(out,open('w1_pairing_trace.json','w'),indent=1)
c=C.Counter()
for o in out:
    nt=(o['near_tag'] or '').replace(' ','').replace('-','')
    c[(o['track'],o['tag'],'sym==sched' if o['sched_in'] and abs(o['symbol_in']-float(o['sched_in']))<1.5 else 'sym!=sched/none','tag_nearest_matches' if nt==o['tag'].replace('-','') else 'nearest_tag='+str(nt),'<=45pt' if (o['near_dist_pt'] or 999)<=45 else '>45pt')]+=1
for k,v in sorted(c.items()): print(v,k)
