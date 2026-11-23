"""R668 live DeepSeek Harness format-1 market discovery, read-only."""
import json
import urllib.request
from urllib.parse import urlsplit
from scripts import r659_plugin_manager as manager

INDEX_URLS=(
 "https://cdn.jsdelivr.net/npm/dsh-plugin-catalog/index.json",
 "https://awesome-dsh-plugin.com/index.json",
)
MAX_BYTES=10*1024*1024

def localized(v):
    if isinstance(v,str):return v[:700]
    if isinstance(v,dict):
        for key in ("zh","zh-cn","en"):
            if isinstance(v.get(key),str):return v[key][:700]
    return ""

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise ValueError("market_redirect_forbidden")

def fetch_index(fetcher=None):
    if fetcher is not None:
        value=fetcher()
        return (json.loads(value) if isinstance(value,bytes) else value),"fixture"
    opener=urllib.request.build_opener(NoRedirect())
    failures=[]
    for url in INDEX_URLS:
        try:
            req=urllib.request.Request(url,headers={
              "Accept":"application/json",
              "User-Agent":"Dafeiyu-Plugin-Discovery/1.0"})
            with opener.open(req,timeout=14) as response:
                if response.status!=200 or urlsplit(response.geturl()).hostname!=urlsplit(url).hostname:
                    raise ValueError("market_response_not_expected")
                raw=response.read(MAX_BYTES+1)
                if len(raw)>MAX_BYTES:raise ValueError("market_too_large")
                return json.loads(raw),url
        except Exception as error:
            failures.append(type(error).__name__)
    raise ValueError("market_network_unavailable:"+",".join(failures))

def discover(home,query="",fetcher=None):
    if not isinstance(query,str) or len(query)>75:raise ValueError("market_invalid_query")
    raw,url=fetch_index(fetcher)
    if not isinstance(raw,dict) or raw.get("format")!=1 or not isinstance(raw.get("plugins"),list):
        raise ValueError("market_format1_required")
    declared=manager.read_profile(home)[0]["dependencies"]
    found=[];total=0
    q=query.casefold().strip()
    for entry in raw["plugins"]:
        if not isinstance(entry,dict):continue
        name=entry.get("name")
        if not isinstance(name,str) or len(name)>180:continue
        title=localized(entry.get("title")) or name
        description=localized(entry.get("description"))
        meta=entry.get("metadata",{})
        cat=meta.get("category","other") if isinstance(meta,dict) else "other"
        if not isinstance(cat,str):cat="other"
        versions=entry.get("versions",[])
        if not isinstance(versions,list):continue
        versions=[v for v in versions if isinstance(v,dict) and
                  isinstance(v.get("version"),str) and
                  isinstance(v.get("source"),dict)]
        if not versions:continue
        version=max(versions,key=lambda v:v.get("publishTimestamp",0)
                    if isinstance(v.get("publishTimestamp"),(int,float)) else 0)
        source_type=version["source"].get("type","unknown")
        if source_type not in ("npm","git"):continue
        haystack=" ".join((name,title,description,cat)).casefold()
        if q and q not in haystack:continue
        total+=1
        if len(found)>=30:continue
        engines=version.get("engines",{})
        engine=engines.get("dsh") if isinstance(engines,dict) else None
        compatibility=("索引要求 DSH "+engine if isinstance(engine,str) and engine
                       else "尚未验证与当前 DSH 版本的兼容性")
        homepage=entry.get("homepage")
        if not isinstance(homepage,str) or not homepage.startswith("https://") or len(homepage)>1000:
            homepage=None
        found.append({
         "id":name,"title":title[:150],"version":version["version"][:60],
         "source":source_type,"scope":cat[:60],
         "description":description[:450],"compatibility":compatibility[:180],
         "declared_locally":name in declared,
         "published_version_verified_online":False,
         "homepage":homepage})
    return {"schema":1,"scope":"companion-only",
            "catalog_type":"live_dsh_format1","query":query,
            "count":len(found),"total_matches":total,"items":found,
            "online_checked":True,"index_url":url,
            "packages_installed":0,"needs_human_install_approval":True}
