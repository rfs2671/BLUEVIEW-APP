# thickness_stroke_test.py: for FLOOR_1 typed walls (gas-change A-100.00, page 1) read the actual page strokes across the wall band and test explanations for printed-vs-measured thickness.
import fitz,csv,collections as C,json
A=618.258;B=751.098
d=fitz.open('C:/Users/asddd/boyland-pdfs/AR - 6.9.26 (Gas change).pdf'); pg=d[0]
segs=[]  # (orient, pos, lo, hi, width, color, layer)
for p in pg.get_drawings():
    for it in p['items']:
        if it[0]!='l': continue
        a,b=it[1],it[2]
        if abs(a.x-b.x)<0.01: segs.append(('v',a.x,min(a.y,b.y),max(a.y,b.y),round(p.get('width') or 0,2),tuple(round(c,2) for c in (p.get('color') or ())),p['layer']))
        elif abs(a.y-b.y)<0.01: segs.append(('h',a.y,min(a.x,b.x),max(a.x,b.x),round(p.get('width') or 0,2),tuple(round(c,2) for c in (p.get('color') or ())),p['layer']))
R=[r for r in csv.DictReader(open('C:/Users/asddd/bv-worktrees/model_export_v09b/elements_filed.csv',encoding='utf8')) if r['class']=='wall' and r['level']=='FLOOR_1' and r['tag'] and 'Gas' in r['source_file']]
def pieces(r):
    if r['footprint_pts_ft']: return [[tuple(map(float,q.split(','))) for q in pc.split(';')] for pc in r['footprint_pts_ft'].split('|')]
    x0,y0,x1,y1=[float(r[k]) for k in('x_min_ft','y_min_ft','x_max_ft','y_max_ft')]; return [[(x0,y0),(x1,y1)]]
out=[]
for r in R:
    for pc in pieces(r):
        xs=[q[0] for q in pc]; ys=[q[1] for q in pc]; x0,x1,y0,y1=min(xs),max(xs),min(ys),max(ys)
        tx,ty=x1-x0,y1-y0
        # long axis in ft_x => page y runs; thickness across ft_y => page x
        if tx>=ty: along=('v',),(x0*18+B,x1*18+B),(y0*18+A,y1*18+A)   # lines are vertical in page (x const) , thickness band in page x
        else: along=('h',),(y0*18+A,y1*18+A),(x0*18+B,x1*18+B)
        orient=along[0][0]; (lo,hi)=along[1]  # lo,hi: long axis range in page coords? fix below
        if tx>=ty: long_lo,long_hi=x0*18+B,x1*18+B; band_lo,band_hi=y0*18+A,y1*18+A; want='v'
        else: long_lo,long_hi=y0*18+A,y1*18+A; band_lo,band_hi=x0*18+B,x1*18+B; want='h'
        # thickness runs across page x for tx>=ty: wall long along page y => lines 'v' (x const) located at band positions
        found=[s for s in segs if s[0]==('v' if tx>=ty else 'h') and band_lo-2<=s[1]<=band_hi+2 and s[3]-s[2]>0.5*(long_hi-long_lo) and s[2]<=long_hi and s[3]>=long_lo]
        # NOTE page rotation: for tx>=ty the thickness band is page-x? ft_y->page_x, so long along page y and lines are 'v'
        out.append(dict(tag=r['tag'],id=r['id'][-6:],thick_in=round(min(tx,ty)*12,2),band=(round(band_lo,2),round(band_hi,2)),lines=sorted(set((round(s[1],2),s[4],s[5],s[6].split('|')[-1]) for s in found))))
json.dump(out,open('thickness_stroke_test.json','w'),indent=1)
for o in out: print(o['tag'],o['id'],o['thick_in'],o['band'],o['lines'])
