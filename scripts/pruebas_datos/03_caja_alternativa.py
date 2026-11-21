import sys, collections, json, requests, numpy as np
from pystac_client import Client
name,lon,lat,h=sys.argv[1],float(sys.argv[2]),float(sys.argv[3]),float(sys.argv[4])
B=[lon-h,lat-h,lon+h,lat+h]; DT="2025-11-21/2026-11-21"
print("==",name,B)
its=list(Client.open("https://earth-search.aws.element84.com/v1").search(collections=["sentinel-2-l2a"],bbox=B,datetime=DT,query={"eo:cloud_cover":{"lt":30}},max_items=1000).items())
c=collections.Counter(i.datetime.strftime("%Y-%m") for i in its)
print("escenas",len(its),"meses",len(c),"min/mes",min(c.values()),dict(sorted(c.items())))
print("tiles",collections.Counter(i.properties.get("grid:code") for i in its))
r=requests.get("https://archive-api.open-meteo.com/v1/archive",params=dict(latitude=lat,longitude=lon,start_date="2025-11-21",end_date="2026-11-20",daily="precipitation_sum,et0_fao_evapotranspiration",timezone="America/Santiago"),timeout=60).json()["daily"]
p=r["precipitation_sum"];print("OM días",len(p),"nulos",sum(v is None for v in p),"lluvia mm",round(sum(v or 0 for v in p)),"ET0 mm",round(sum(v or 0 for v in r["et0_fao_evapotranspiration"])))
m=collections.defaultdict(float)
for t,v in zip(r["time"],p): m[t[:7]]+=v or 0
print({k:round(v) for k,v in m.items()})
e=requests.get("https://climatologia.meteochile.gob.cl/application/servicios/getEstacionesRedEma",timeout=30).json()["datosEstacion"]
near=sorted(((((float(s["latitud"])-lat)*111)**2+((float(s["longitud"])-lon)*93)**2)**.5,s["codigoNacional"],s["nombreEstacion"],s["altura"]) for s in e)[:5]
for d,c_,n,a in near: print("DMC",c_,n.encode('latin1','ignore').decode('utf8','ignore') or n,a,"m",round(d),"km")
