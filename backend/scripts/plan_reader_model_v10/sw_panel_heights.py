# sw_panel_heights.py: every X-brace panel box on S-302 (ST - 7.29.26.pdf p12): diagonal lines and quads of layer SET_STEEL_JOIST clustered by overlapping bbox. Output sw_panel_heights.csv.
import fitz,csv
d=fitz.open('C:/Users/asddd/boyland-pdfs/ST - 7.29.26.pdf'); p=d[11]
B=[]
for x in p.get_drawings():
    if x.get('layer')!='SET_STEEL_JOIST': continue
    for it in x['items']:
        if it[0]=='l':
            a,b=it[1],it[2]; dx,dy=abs(a.x-b.x),abs(a.y-b.y)
            if dx>60 and dy>60 and 0.5<dx/dy<2: B.append([min(a.x,b.x),max(a.x,b.x),min(a.y,b.y),max(a.y,b.y),'line'])
        elif it[0]=='qu':
            q=it[1]; xs=[q.ul.x,q.ur.x,q.lr.x,q.ll.x]; ys=[q.ul.y,q.ur.y,q.lr.y,q.ll.y]
            if max(xs)-min(xs)>60 and max(ys)-min(ys)>60: B.append([min(xs),max(xs),min(ys),max(ys),'quad'])
def ov(a,b):
    ix=min(a[1],b[1])-max(a[0],b[0]); iy=min(a[3],b[3])-max(a[2],b[2])
    return ix>0.5*min(a[1]-a[0],b[1]-b[0]) and iy>0.5*min(a[3]-a[2],b[3]-b[2])
C=[]
for b in B:
    m=[c for c in C if any(ov(b,z) for z in c)]
    for c in m: C.remove(c)
    C.append(sum(m,[])+[b])
rows=[]
for c in C:
    x0=min(z[0] for z in c);x1=max(z[1] for z in c);y0=min(z[2] for z in c);y1=max(z[3] for z in c)
    rows.append(dict(x0=round(x0,1),x1=round(x1,1),y0=round(y0,1),y1=round(y1,1),members=len(c),kinds='+'.join(sorted({z[4] for z in c})),height_pt=round(y1-y0,1),width_pt=round(x1-x0,1),height_ft_at_0_0741=round((y1-y0)*0.0741,2)))
rows.sort(key=lambda r:(round(r['x0']/60),r['y0']))
for i,r in enumerate(rows,1): r['n']=i
csv.DictWriter(open('sw_panel_heights.csv','w',newline=''),fieldnames=list(rows[0])).writeheader()
w=csv.DictWriter(open('sw_panel_heights.csv','w',newline=''),fieldnames=['n']+[k for k in rows[0] if k!='n']); w.writeheader(); w.writerows(rows)
for r in rows: print(r)
