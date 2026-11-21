import time, collections, json, sys
import numpy as np, rasterio
from rasterio.windows import from_bounds
from rasterio.warp import transform_bounds
from pystac_client import Client
BBOX=[-71.35,-32.60,-70.85,-32.10]
DT="2025-11-21/2026-11-21"
t=time.time()
cat=Client.open("https://earth-search.aws.element84.com/v1")
s=cat.search(collections=["sentinel-2-l2a"],bbox=BBOX,datetime=DT,query={"eo:cloud_cover":{"lt":30}},max_items=1000)
items=list(s.items())
print("ES search s:",round(time.time()-t,1),"items",len(items))
c=collections.Counter(i.datetime.strftime("%Y-%m") for i in items)
for k in sorted(c): print(k,c[k])
print("min/mes",min(c.values()),"meses",len(c))
print("assets",sorted(items[0].assets)[:40])
json.dump([i.id for i in items],open("/tmp/ids.json","w"))
# clip ~10ha around a point in the valley (Petorca ~ -70.93,-32.25)
cx,cy=-70.93,-32.25
d=0.0016  # ~ 0.32km -> ~10ha
b=[cx-d,cy-d*1.0,cx+d,cy+d]
# pick lowest-cloud item that covers the point
cands=[i for i in items if i.bbox[0]<cx<i.bbox[2] and i.bbox[1]<cy<i.bbox[3]]
cands.sort(key=lambda i:i.properties["eo:cloud_cover"])
it=cands[0]; print("item",it.id,it.properties["eo:cloud_cover"])
def read(a):
    with rasterio.Env(AWS_NO_SIGN_REQUEST="YES"):
        with rasterio.open(it.assets[a].href) as ds:
            bb=transform_bounds("EPSG:4326",ds.crs,*b)
            w=from_bounds(*bb,transform=ds.transform)
            return ds.read(1,window=w,boundless=False).astype("float32"),ds.res
t=time.time()
red,r=read("red");nir,_=read("nir");sw,r2=read("swir16");scl,_=read("scl")
print("read s",round(time.time()-t,1),red.shape,nir.shape,sw.shape,r,r2)
print("area ha",red.shape[0]*red.shape[1]*r[0]*r[1]/1e4)
import scipy.ndimage as nd
sw=nd.zoom(sw,(red.shape[0]/sw.shape[0],red.shape[1]/sw.shape[1]),order=1)
# scale: L2A earth-search offset -1000 /10000 (baseline>=04.00)
def refl(x): return (x-1000)/10000 if it.properties.get("s2:processing_baseline","0")>="04.00" else x/10000
R,N,W=refl(red),refl(nir),refl(sw)
ndvi=(N-R)/(N+R);ndmi=(N-W)/(N+W)
for n,a in(("ndvi",ndvi),("ndmi",ndmi)):
    print(n,"min",np.nanmin(a),"max",np.nanmax(a),"mean",np.nanmean(a),"nan",int(np.isnan(a).sum()))
print("baseline",it.properties.get("s2:processing_baseline"),"SCL counts",dict(zip(*np.unique(scl,return_counts=True))))
