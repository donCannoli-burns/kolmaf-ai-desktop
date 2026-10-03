#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, os, re, shutil, sqlite3, sys, urllib.request
from pathlib import Path

AUTH = {"REFERENCE_ONLY","GUIDANCE_ONLY","OBSERVATION_ONLY","TEST_ONLY","LOCAL_DOCUMENT_WRITE","GOVERNED_MUTATION","STRUCTURAL_DENY"}

def root_from_here() -> Path:
    return Path(__file__).resolve().parents[1]

def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))

def env_paths(root: Path, project_root: Path | None):
    kol = Path(os.environ.get("KOLMAFIA_HOME", str(Path.home()/".kolmafia"))).expanduser().resolve()
    proj = (project_root or Path(os.environ.get("KOLMAF_PROJECT_ROOT", os.getcwd()))).expanduser().resolve()
    return {"BUNDLE_ROOT": str(root), "KOLMAFIA_HOME": str(kol), "PROJECT_ROOT": str(proj)}

def expand(s: str, vals: dict[str,str]) -> str:
    for k,v in vals.items(): s=s.replace("${"+k+"}",v)
    return s

def providers(root: Path): return load_json(root/"data/providers/registry.json")["providers"]
def capabilities(root: Path): return load_json(root/"data/capabilities/registry.json")["capabilities"]

def discover(root: Path, project_root: Path | None=None):
    vals=env_paths(root, project_root); out=[]
    for p in providers(root):
        req=[Path(expand(x,vals)) for x in p.get("required",[])]
        opt=[Path(expand(x,vals)) for x in p.get("optional",[])]
        missing=[str(x) for x in req if not x.exists()]
        optional_missing=[str(x) for x in opt if not x.exists()]
        status="READY" if not missing else "MISSING"
        if not missing and optional_missing: status="DEGRADED"
        out.append({
            "id":p["id"],"name":p["name"],"status":status,"authority":p["authority"],
            "required":[{"path":str(x),"exists":x.exists()} for x in req],
            "optional":[{"path":str(x),"exists":x.exists()} for x in opt],
            "capabilities":p.get("capabilities",[]),"canonical_alias":p.get("canonical_alias"),
            "activation":p.get("activation"),"context_cost":p.get("context_cost"),
        })
    return {"schema":"maf-ai-provider-health-v1","providers":out,"environment":vals}

def native_capability_status(root: Path, health: dict):
    vals = health.get("environment", {})
    prov_ready = {p["id"]: (p.get("status") == "READY") for p in health.get("providers", [])}
    out = {}
    for c in capabilities(root):
        if "native_owner" not in c:
            continue
        checks = {}
        try:
            checks["canonical_exists"] = bool(c.get("helper_canonical")) and Path(c["helper_canonical"]).is_file()
        except OSError:
            checks["canonical_exists"] = False
        installed_bytes = None
        if c.get("helper_installed"):
            try:
                p = Path(expand(c["helper_installed"], vals))
                if p.is_file():
                    installed_bytes = p.read_bytes()
            except OSError:
                installed_bytes = None
        checks["installed_exists"] = installed_bytes is not None
        checks["hash_matches"] = bool(
            installed_bytes is not None and c.get("helper_sha256")
            and hashlib.sha256(installed_bytes).hexdigest() == c["helper_sha256"]
        )
        if not checks["canonical_exists"]:
            status = "UNAVAILABLE"
        elif not checks["installed_exists"] or not checks["hash_matches"]:
            status = "DEGRADED"
        elif not prov_ready.get(c.get("provider"), False):
            status = "DEGRADED"
        else:
            status = "READY"
        out[c["id"]] = {
            "status": status,
            "authority": c.get("authority"),
            "freshness": c.get("freshness", "UNKNOWN"),
            "checks": checks,
        }
    return out

def compile_runtime(root: Path, project_root: Path | None=None):
    rt=root/"agentflow/runtime"; rt.mkdir(parents=True,exist_ok=True)
    health=discover(root,project_root)
    (rt/"provider-health.json").write_text(json.dumps(health,indent=2,sort_keys=True)+"\n")
    (rt/"providers.json").write_text(json.dumps({"schema":"maf-ai-runtime-providers-v1","providers":providers(root)},indent=2,sort_keys=True)+"\n")
    (rt/"capabilities.json").write_text(json.dumps({"schema":"maf-ai-runtime-capabilities-v1","capabilities":capabilities(root)},indent=2,sort_keys=True)+"\n")
    degraded=[{"id":x["id"],"status":x["status"]} for x in health["providers"] if x["status"]!="READY"]
    (rt/"degraded.json").write_text(json.dumps({"schema":"maf-ai-degraded-v1","providers":degraded},indent=2,sort_keys=True)+"\n")
    advertised=[c["id"] for c in capabilities(root) if c.get("activation")=="always"]
    (rt/"tool-session.json").write_text(json.dumps({"schema":"maf-ai-tool-session-v1","advertised":advertised,"lazy_provider_count":sum(1 for x in health["providers"] if x.get("activation")=="lazy")},indent=2,sort_keys=True)+"\n")
    compat={"schema":"maf-ai-compatibility-v1","python":sys.version.split()[0],"opencode":shutil.which("opencode"),"node":shutil.which("node"),"bun":shutil.which("bun")}
    (rt/"compatibility.json").write_text(json.dumps(compat,indent=2,sort_keys=True)+"\n")
    native_caps=native_capability_status(root,health)
    bootstrap={"schema":"maf-ai-runtime-bootstrap-v1","status":"READY","mode":"offline","canonical_root":str(root),"project_root":health["environment"]["PROJECT_ROOT"],"providers":{x["id"]:x["status"] for x in health["providers"]},"capability_registry":"agentflow/runtime/capabilities.json","native_capabilities":native_caps,"live_write":{"status":"DISABLED_BY_BOOTSTRAP","authority":"don-action-broker-only"},"degraded":degraded}
    (rt/"lead-bootstrap.json").write_text(json.dumps(bootstrap,indent=2,sort_keys=True)+"\n")
    return bootstrap

def capability_search(root:Path,q:str):
    q=q.lower().strip(); arr=[]
    pmap={p["id"]:p for p in providers(root)}
    for c in capabilities(root):
        text=" ".join([c["id"],c["provider"],c["authority"],pmap.get(c["provider"],{}).get("name","")]).lower()
        if not q or q in text: arr.append(c)
    return arr

def resolve(root:Path,ref:str):
    for p in providers(root):
        alias=p.get("canonical_alias") or ""
        if ref==alias.rstrip("/") or (alias and ref.startswith(alias)) or ref=="kolmaf://provider/"+p["id"]:
            return {"found":True,"provider":p["id"],"native_identity":p.get("native_identity"),"canonical_alias":alias,"authority":p["authority"]}
    return {"found":False,"error":"NOT_FOUND","ref":ref}

def matrix_search(root:Path,q:str,limit:int,project_root:Path|None):
    vals=env_paths(root,project_root); path=Path(vals["KOLMAFIA_HOME"])/"data/html-matrix/hyper-data.json"
    if not path.exists(): return {"ok":False,"error":"PROVIDER_MISSING","path":str(path)}
    data=load_json(path); nodes=data.get("nodes",data if isinstance(data,list) else [])
    toks=[x for x in re.split(r"\W+",q.lower()) if x]
    scored=[]
    for n in nodes:
        text=" ".join(str(n.get(k,"")) for k in ("name","description","category","kind","authority","tier","effect","surface","syntax"))+" "+" ".join(n.get("tags",[]) or [])
        low=text.lower(); hit=sum(1 for t in toks if t in low)
        if hit: scored.append((hit,n))
    scored.sort(key=lambda x:(-x[0],str(x[1].get("id",""))))
    return {"ok":True,"query":q,"results":[{"id":n.get("id"),"name":n.get("name"),"pointer":n.get("pointer"),"authority":n.get("authority"),"tier":n.get("tier"),"score":s} for s,n in scored[:limit]]}

def tokens_item(root:Path,item_id:int,project_root:Path|None):
    vals=env_paths(root,project_root); db=Path(vals["KOLMAFIA_HOME"])/"data/dol.sqlite"
    if not db.exists(): return {"ok":False,"error":"PROVIDER_MISSING","path":str(db)}
    uri=f"file:{db}?mode=ro"
    con=sqlite3.connect(uri,uri=True); con.row_factory=sqlite3.Row
    try:
        tables={r[0] for r in con.execute("select name from sqlite_master where type='table'")}
        table=next((x for x in ("items","item") if x in tables),None)
        if not table: return {"ok":False,"error":"ITEM_TABLE_NOT_FOUND","tables":sorted(tables)[:30]}
        cols=[r[1] for r in con.execute(f"pragma table_info({table})")]
        idcol=next((x for x in ("id","item_id","itemId") if x in cols),None)
        if not idcol: return {"ok":False,"error":"ITEM_ID_COLUMN_NOT_FOUND","columns":cols}
        row=con.execute(f"select * from {table} where {idcol}=? limit 1",(item_id,)).fetchone()
        return {"ok":True,"item":dict(row) if row else None,"table":table}
    finally: con.close()

def goblin_search(root:Path,q:str,project_root:Path|None):
    vals=env_paths(root,project_root); path=Path(vals["KOLMAFIA_HOME"])/"data/kol-goblin-docs/matrix.tsv"
    if not path.exists(): return {"ok":False,"error":"PROVIDER_MISSING","path":str(path)}
    lines=path.read_text(encoding="utf-8",errors="replace").splitlines(); low=q.lower()
    hits=[ln for ln in lines if low in ln.lower()][:50]
    return {"ok":True,"query":q,"matches":hits}

def safe_json_status(path:Path):
    if not path.exists(): return {"ok":False,"error":"NOT_FOUND","path":str(path)}
    try: return {"ok":True,"path":str(path),"data":load_json(path)}
    except Exception as e: return {"ok":False,"error":"INVALID_JSON","detail":str(e),"path":str(path)}

def memory_status(root:Path,project_root:Path|None):
    vals=env_paths(root,project_root); base=Path(vals["KOLMAFIA_HOME"])/"kolmaf-ai/memory"
    return {"manifest":safe_json_status(base/"manifest.json"),"runtime":safe_json_status(base/"state/runtime.json")}

def sandbox_status(root:Path,project_root:Path|None):
    vals=env_paths(root,project_root); return safe_json_status(Path(vals["KOLMAFIA_HOME"])/"data/kol-agent-sandbox/agent-sandbox-contract.json")

def artifact_status(root:Path,project_root:Path|None):
    vals=env_paths(root,project_root); base=Path(vals["KOLMAFIA_HOME"])/"data/doc_edit"
    # Deliberately never reads service.token.
    out={"ok":base.exists(),"base":str(base),"service_token_read":False}
    for name in ("agent-status.json","system-status.json"):
        if (base/name).exists(): out[name]=safe_json_status(base/name)
    return out

def kingdomsitter_status():
    url="http://127.0.0.1:10423/health"
    try:
        with urllib.request.urlopen(url,timeout=1.5) as r:
            raw=r.read(65536)
        data=json.loads(raw.decode("utf-8"))
        allow={k:data.get(k) for k in ("ok","name","parser_backend","execution_authority","state_seen","last_state_update") if k in data}
        return {"ok":True,"health":allow}
    except Exception as e: return {"ok":False,"error":type(e).__name__}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--root",type=Path,default=root_from_here()); ap.add_argument("--project-root",type=Path)
    sub=ap.add_subparsers(dest="cmd",required=True)
    sub.add_parser("compile")
    p=sub.add_parser("capabilities"); p.add_argument("query",nargs="?",default="")
    p=sub.add_parser("provider-status"); p.add_argument("provider",nargs="?")
    p=sub.add_parser("resolve"); p.add_argument("ref")
    p=sub.add_parser("matrix-search"); p.add_argument("query"); p.add_argument("--limit",type=int,default=12)
    p=sub.add_parser("tokens-item"); p.add_argument("item_id",type=int)
    p=sub.add_parser("goblin-search"); p.add_argument("query")
    sub.add_parser("memory-status"); sub.add_parser("sandbox-status"); sub.add_parser("artifact-status"); sub.add_parser("kingdomsitter-status"); sub.add_parser("bootstrap"); sub.add_parser("native-status")
    a=ap.parse_args(); root=a.root.expanduser().resolve()
    if a.cmd=="compile": out=compile_runtime(root,a.project_root)
    elif a.cmd=="capabilities": out={"schema":"maf-ai-capability-search-v1","query":a.query,"results":capability_search(root,a.query)}
    elif a.cmd=="provider-status":
        h=discover(root,a.project_root); out=h if not a.provider else next((x for x in h["providers"] if x["id"]==a.provider),{"error":"NOT_FOUND"})
    elif a.cmd=="resolve": out=resolve(root,a.ref)
    elif a.cmd=="matrix-search": out=matrix_search(root,a.query,a.limit,a.project_root)
    elif a.cmd=="tokens-item": out=tokens_item(root,a.item_id,a.project_root)
    elif a.cmd=="goblin-search": out=goblin_search(root,a.query,a.project_root)
    elif a.cmd=="memory-status": out=memory_status(root,a.project_root)
    elif a.cmd=="sandbox-status": out=sandbox_status(root,a.project_root)
    elif a.cmd=="artifact-status": out=artifact_status(root,a.project_root)
    elif a.cmd=="kingdomsitter-status": out=kingdomsitter_status()
    elif a.cmd=="bootstrap": out=compile_runtime(root,a.project_root)
    elif a.cmd=="native-status": out={"schema":"maf-ai-native-capabilities-v1","capabilities":native_capability_status(root,discover(root,a.project_root))}
    print(json.dumps(out,indent=2,sort_keys=True))
if __name__=="__main__": main()
