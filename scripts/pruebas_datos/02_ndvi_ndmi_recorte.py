import numpy as np, rasterio, scipy.ndimage as nd
from rasterio.windows import from_bounds
from rasterio.warp import transform_bounds
from pystac_client import Client
cx,cy,d=-70.93,-32.25,0.0016
b=[cx-d,cy-d,cx+d,cy+d]
cat=Client.open("https://earth-search.aws.element84.com/v1")
it=next(cat.search(collections=["sentinel-2-l2a"],ids=["S2C_19HCE_20260402_0_L2A"]).items())
print({k:it.assets[k].extra_fields.get("raster:bands") for k in("red","nir","swir16")})
def read(a):
    with rasterio.Env(AWS_NO_SIGN_REQUEST="YES"):
        with rasterio.open(it.assets[a].href) as ds:
            w=from_bounds(*transform_bounds("EPSG:4326",ds.crs,*b),transform=ds.transform)
            return ds.read(1,window=w).astype("float32")
red,nir,sw,scl=[read(a) for a in("red","nir","swir16","scl")]
print("raw red min/max",red.min(),red.max(),"nir",nir.min(),nir.max())
sw=nd.zoom(sw,(red.shape[0]/sw.shape[0],red.shape[1]/sw.shape[1]),order=1)
scl=nd.zoom(scl,(red.shape[0]/scl.shape[0],red.shape[1]/scl.shape[1]),order=0)
f=lambda x:np.clip(x*1e-4-0.1,0,1)
R,N,W=f(red),f(nir),f(sw)
ok=(red>0)&(nir>0)&(sw>0)&np.isin(scl,[4,5,6,7])
print("valid px",ok.sum(),"/",ok.size)
for n,a in(("ndvi",(N-R)/np.maximum(N+R,1e-6)),("ndmi",(N-W)/np.maximum(N+W,1e-6))):
    v=a[ok];print(n,v.min(),v.max(),v.mean(),"nan",int(np.isnan(v).sum()))
