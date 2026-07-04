#!/usr/bin/env python3
"""Gerador Dashboard Lançamento Gratuito v2"""

import pandas as pd, json, re, hashlib, requests
from datetime import date
from pathlib import Path

# ══════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════

SHEET_ID         = "1jw5233AdiGs3FRHmG-uIQBxJpFULPFMGA0OptoVJqKk"
TEMPLATE_FILE    = "dashboard_lancamento_gratuito.html"
OUTPUT_FILE      = "index.html"

NOME_CLIENTE     = "Sergio Cripto"
LOGO_LETRA       = "SC"
COR_ACENTO       = "#B8860B"

LANCAMENTO_COD   = "IP02"        # filtra campanhas; "" = ver tudo
USAR_PESQUISA    = True            # False = oculta aba Pesquisa

# ══ MOEDA ══════════════════════════════════════════════
# Escolha a moeda do cliente:
#   "BRL"  → R$ (Real Brasileiro)
#   "USD"  → $ (Dólar Americano)
#   "EUR"  → € (Euro)
MOEDA            = "EUR"

# Metas do funil — define cores (verde/amarelo/vermelho)
CPL_BOM          = 9.06    # Custo por Lead ≤ 5 → verde | 5-10 → amarelo | acima → vermelho
CPL_MEDIO        = 12.0
CTR_BOM          = 1.0    # CTR ≥ 1.2% → verde | 0.8-1.2% → amarelo | abaixo → vermelho
CTR_MEDIO        = 0.8
CR_BOM           = 65.0   # Connect Rate ≥ 40% → verde | 25-40% → amarelo | abaixo → vermelho
CR_MEDIO         = 60.0
TX_CONV_BOM      = 25.0   # Taxa Conversão (Lead/PV) ≥ 30% → verde | 15-30% → amarelo | abaixo → vermelho
TX_CONV_MEDIO    = 18.0
CPM_BOM          = 5.0    
CPM_MEDIO        = 12.0

# ══════════════════════════════════════════════════════
# Mapeamento de moeda → símbolo e label
MOEDA_MAP = {
    "BRL": {"simbolo": "R$", "label": "Real (R$)"},
    "USD": {"simbolo": "$",  "label": "Dólar ($)"},
    "EUR": {"simbolo": "€",  "label": "Euro (€)"},
}
_moeda_cfg = MOEDA_MAP.get(MOEDA, MOEDA_MAP["BRL"])
MOEDA_SIMBOLO = _moeda_cfg["simbolo"]
MOEDA_LABEL   = _moeda_cfg["label"]

# ══════════════════════════════════════════════════════
def sheet_url(t): return f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={t}"
URL_META = sheet_url("meta-ads")
URL_PES  = sheet_url("Pesquisa")
URL_GA   = sheet_url("breakdown-gender-age")
URL_PT   = sheet_url("breakdown-platform")

def to_num(s):
    if pd.api.types.is_numeric_dtype(s): return s.fillna(0)
    clean = s.astype(str).str.strip().str.replace("R$","",regex=False).str.replace("$","",regex=False).str.replace("€","",regex=False).str.strip()
    if clean.str.contains(r"\d,\d", regex=True).any():
        clean = clean.str.replace(".","",regex=False).str.replace(",",".",regex=False)
    return pd.to_numeric(clean, errors="coerce").fillna(0)

def safe(v):
    if v is None or (isinstance(v,float) and pd.isna(v)): return None
    return round(float(v),2) if float(v)!=0 else None

def download_thumb(url, d):
    if not url or str(url)=="nan": return ""
    try:
        ext=".png" if ".png" in url.lower() else ".jpg"
        fname=hashlib.md5(url.encode()).hexdigest()[:16]+ext
        fp=d/fname
        if not fp.exists():
            r=requests.get(url,timeout=10,headers={"User-Agent":"Mozilla/5.0"})
            if r.status_code==200: fp.write_bytes(r.content)
            else: return ""
        return "imgs/"+fname
    except: return ""

# ══ META ADS ══════════════════════════════════════════
def load_meta():
    print("  Lendo meta-ads...")
    df=pd.read_csv(URL_META)
    df=df.rename(columns={
        "Date":"date","Campaign Name":"campaign","Adset Name":"adset",
        "Ad Name":"ad","Thumbnail URL":"thumb","Status":"status",
        "Spend (Cost, Amount Spent)":"spend",
        "Impressions":"impressions",
        "Action Link Clicks":"link_clicks",
        "Action Landing Page View":"page_view",
        "Action Leads":"leads"
    })
    df["date"]=pd.to_datetime(df["date"],errors="coerce")
    for c in ["spend","impressions","link_clicks","page_view","leads"]:
        if c in df.columns: df[c]=to_num(df[c])
    if "status" in df.columns:
        df["status"]=df["status"].astype(str).str.strip().str.upper()
    df["is_lct"]=df["campaign"].str.contains(LANCAMENTO_COD,na=False,case=False) if LANCAMENTO_COD else True
    df=df.dropna(subset=["date"])
    print(f"     {len(df)} linhas | {df['date'].min().date()} → {df['date'].max().date()}")
    return df

def calc_kpis(p):
    sp=float(p["spend"].sum()); imp=float(p["impressions"].sum())
    lc=float(p["link_clicks"].sum()); pv=float(p["page_view"].sum())
    ld=float(p["leads"].sum())
    return {
        "spend":round(sp,2),"impressions":int(imp),"link_clicks":int(lc),
        "page_view":int(pv),"leads":int(ld),
        "ctr":   round(lc/imp*100,2) if imp>0 else None,
        "connect_rate":round(pv/lc*100,2) if lc>0 else None,
        "tx_conv":round(ld/pv*100,2) if pv>0 else None,
        "cpl":   round(sp/ld,2) if ld>0 else None,
        "cpm":   round(sp/imp*1000,2) if imp>0 else None
    }

def meta_kpis(df):
    return {"lct":calc_kpis(df[df["is_lct"]]),"all":calc_kpis(df)}

def build_daily(p):
    agg=p.groupby("date").agg(
        spend=("spend","sum"),impressions=("impressions","sum"),
        link_clicks=("link_clicks","sum"),page_view=("page_view","sum"),
        leads=("leads","sum")
    ).reset_index().sort_values("date")
    out={k:[] for k in ["days","spend","impressions","link_clicks","page_view","leads","ctr","connect_rate","tx_conv","cpl","cpm"]}
    for _,r in agg.iterrows():
        sp=float(r["spend"]); imp=float(r["impressions"]); lc=float(r["link_clicks"])
        pv=float(r["page_view"]); ld=float(r["leads"])
        out["days"].append(r["date"].strftime("%d/%m"))
        out["spend"].append(round(sp,2)); out["impressions"].append(int(imp))
        out["link_clicks"].append(int(lc)); out["page_view"].append(int(pv))
        out["leads"].append(int(ld))
        out["ctr"].append(round(lc/imp*100,2) if imp>0 else None)
        out["connect_rate"].append(round(pv/lc*100,2) if lc>0 else None)
        out["tx_conv"].append(round(ld/pv*100,2) if pv>0 else None)
        out["cpl"].append(round(sp/ld,2) if ld>0 else None)
        out["cpm"].append(round(sp/imp*1000,2) if imp>0 else None)
    return out

def meta_daily(df):
    return {"lct":build_daily(df[df["is_lct"]]),"all":build_daily(df)}

def meta_daily_camps(df):
    result={"lct":{},"all":{}}
    for key,subset in [("lct",df[df["is_lct"]]),("all",df)]:
        for camp in subset["campaign"].unique():
            result[key][camp]=build_daily(subset[subset["campaign"]==camp])
    return result

def meta_raw(df):
    rows=[]
    agg=df.groupby(["date","campaign","adset","is_lct"]).agg(
        spend=("spend","sum"),leads=("leads","sum"),
        impressions=("impressions","sum"),link_clicks=("link_clicks","sum"),
        page_view=("page_view","sum")
    ).reset_index()
    for _,r in agg.iterrows():
        rows.append({
            "d":r["date"].strftime("%d/%m"),"c":str(r["campaign"]),"a":str(r["adset"]),
            "lct":bool(r["is_lct"]),"sp":round(float(r["spend"]),2),
            "ld":int(r["leads"]),"imp":int(r["impressions"]),
            "lc":int(r["link_clicks"]),"pv":int(r["page_view"])
        })
    return rows

# ══ STATUS (bolinha verde/cinza) ══════════════════════
_STATUS_PRIORITY=["ACTIVE","WITH_ISSUES","PAUSED","ADSET_PAUSED","CAMPAIGN_PAUSED","ARCHIVED"]

def _pick_status(group):
    """Status atual: linha de data mais recente. Em empate, preferir ACTIVE; senão usar prioridade."""
    if "status" not in group.columns or group.empty: return ""
    g=group.dropna(subset=["date"])
    if g.empty: return ""
    max_date=g["date"].max()
    latest=g[g["date"]==max_date]
    statuses=set(latest["status"].astype(str).str.upper())
    for s in _STATUS_PRIORITY:
        if s in statuses: return s
    return str(latest["status"].iloc[0])

def build_status_maps(df):
    """Retorna 3 dicts: camp_status, adset_status, ad_status."""
    camp_status={}; adset_status={}; ad_status={}
    if "status" not in df.columns: return camp_status, adset_status, ad_status
    for camp,g in df.groupby("campaign"):
        camp_status[str(camp)]=_pick_status(g)
        for adset,g2 in g.groupby("adset"):
            adset_status[(str(camp),str(adset))]=_pick_status(g2)
            for ad,g3 in g2.groupby("ad"):
                ad_status[(str(camp),str(adset),str(ad))]=_pick_status(g3)
    return camp_status, adset_status, ad_status

def meta_tables_period(df, p, img_dir, camp_status=None, adset_status=None, ad_status=None):
    camp_status=camp_status or {}; adset_status=adset_status or {}; ad_status=ad_status or {}
    def ag(sub,cols): return sub.groupby(cols).agg(spend=("spend","sum"),impressions=("impressions","sum"),link_clicks=("link_clicks","sum"),page_view=("page_view","sum"),leads=("leads","sum")).reset_index()

    def calc_row(r):
        sp=round(float(r["spend"]),2); imp=int(r["impressions"]); lc=int(r["link_clicks"])
        pv=int(r["page_view"]); ld=int(r["leads"])
        return {"spend":sp,"imp":imp,"lc":lc,"pv":pv,"ld":ld,
            "ctr":round(lc/imp*100,2) if imp>0 else None,
            "cr":round(pv/lc*100,2) if lc>0 else None,
            "tx_cv":round(ld/pv*100,2) if pv>0 else None,
            "cpl":round(sp/ld,2) if ld>0 else None,
            "cpm":round(sp/imp*1000,2) if imp>0 else None}

    camps_agg=ag(p,"campaign")
    camps=[{"n":str(r["campaign"]),"status":camp_status.get(str(r["campaign"]),""),**calc_row(r)} for _,r in camps_agg.sort_values("leads",ascending=False).iterrows()]

    adsets_agg=ag(p,["campaign","adset"])
    adsets=[{"n":str(r["adset"]),"camp":str(r["campaign"]),
             "status":adset_status.get((str(r["campaign"]),str(r["adset"])),""),
             **calc_row(r)} for _,r in adsets_agg.sort_values("leads",ascending=False).iterrows()]

    df_full_thumb=df[df["thumb"].notna()&(df["thumb"].astype(str)!="nan")] if "thumb" in df.columns else pd.DataFrame()
    thumb_map={}
    for _,r in df_full_thumb.iterrows():
        k=(str(r["ad"]),str(r["adset"]),str(r["campaign"]))
        if k not in thumb_map: thumb_map[k]=download_thumb(str(r["thumb"]),img_dir)

    ads_agg=p.groupby(["ad","adset","campaign"]).agg(spend=("spend","sum"),impressions=("impressions","sum"),link_clicks=("link_clicks","sum"),leads=("leads","sum")).reset_index().sort_values("leads",ascending=False)
    ads=[]
    for _,r in ads_agg.iterrows():
        sp=round(float(r["spend"]),2); imp=int(r["impressions"]); lc=int(r["link_clicks"]); ld=int(r["leads"])
        k=(str(r["ad"]),str(r["adset"]),str(r["campaign"]))
        ads.append({"n":str(r["ad"]),"adset":str(r["adset"]),"camp":str(r["campaign"]),
            "status":ad_status.get((str(r["campaign"]),str(r["adset"]),str(r["ad"])),""),
            "thumb":thumb_map.get(k,""),"spend":sp,"imp":imp,"lc":lc,"ld":ld,
            "ctr":round(lc/imp*100,2) if imp>0 else None,
            "cpl":round(sp/ld,2) if ld>0 else None})
    return {"camps":camps,"adsets":adsets,"ads":ads}

def meta_tables(df, img_dir):
    hoje=pd.Timestamp(date.today())
    camp_status, adset_status, ad_status = build_status_maps(df)
    result={"lct":{},"all":{}}
    for key,subset in [("lct",df[df["is_lct"]]),("all",df)]:
        for pname,n in [("1",1),("7",7),("14",14),("30",30),("all",0)]:
            p=subset[subset["date"]>=hoje-pd.Timedelta(days=n-1)] if n>0 else subset
            result[key][pname]=meta_tables_period(df,p,img_dir,camp_status,adset_status,ad_status)
            print(f"     [{key}][{pname}]: {len(result[key][pname]['camps'])} camps | {len(result[key][pname]['ads'])} ads")
    return result

def meta_breakdowns(df):
    print("  Lendo breakdowns...")
    hoje_bd=pd.Timestamp(date.today())
    AGE_ORDER=["18-24","25-34","35-44","45-54","55-64","65+"]
    def seg(agg,dim):
        agg=agg[agg["spend"]>0].copy()
        agg["cpl"]=(agg["spend"]/agg["leads"]).where(agg["leads"]>0).round(2)
        return [{"n":str(r[dim]),"spend":round(float(r["spend"]),2),"ld":int(r["leads"]),"cpl":safe(r["cpl"])} for _,r in agg.iterrows()]
    try:
        df_ga=pd.read_csv(URL_GA)
        df_ga["date"]=pd.to_datetime(df_ga["Date"],errors="coerce")
        df_ga["spend"]=to_num(df_ga["Spend (Cost, Amount Spent)"])
        df_ga["leads"]=to_num(df_ga["Action Leads"])
        df_ga["age"]=df_ga["Age (Breakdown)"].astype(str)
        df_ga["gender"]=df_ga["Gender (Breakdown)"].astype(str)
        if "Campaign Name" in df_ga.columns and LANCAMENTO_COD:
            df_ga["is_lct"]=df_ga["Campaign Name"].str.contains(LANCAMENTO_COD,na=False,case=False)
        else:
            df_ga["is_lct"]=True
        df_ga=df_ga.dropna(subset=["date"])
    except Exception as e: print(f"  Aviso GA: {e}"); df_ga=pd.DataFrame()
    try:
        df_pt=pd.read_csv(URL_PT)
        df_pt["date"]=pd.to_datetime(df_pt["Date"],errors="coerce")
        df_pt["spend"]=to_num(df_pt["Spend (Cost, Amount Spent)"])
        df_pt["leads"]=to_num(df_pt["Action Leads"])
        df_pt["platform"]=df_pt["Platform Position (Breakdown)"].astype(str)
        if "Campaign Name" in df_pt.columns and LANCAMENTO_COD:
            df_pt["is_lct"]=df_pt["Campaign Name"].str.contains(LANCAMENTO_COD,na=False,case=False)
        else:
            df_pt["is_lct"]=True
        df_pt=df_pt.dropna(subset=["date"])
    except Exception as e: print(f"  Aviso PT: {e}"); df_pt=pd.DataFrame()

    result={}
    for pname,n in [("1",1),("7",7),("14",14),("30",30),("all",0)]:
        start=hoje_bd-pd.Timedelta(days=n-1) if n>0 else None
        for lname,lct_filter in [("lct",True),("all",None)]:
            if len(df_ga)>0:
                pga=df_ga if lct_filter is None else df_ga[df_ga["is_lct"]]
                pga=pga[(pga["date"]>=start)&(pga["date"]<=hoje_bd)] if n>0 else pga
            else: pga=df_ga
            if len(df_pt)>0:
                ppt=df_pt if lct_filter is None else df_pt[df_pt["is_lct"]]
                ppt=ppt[(ppt["date"]>=start)&(ppt["date"]<=hoje_bd)] if n>0 else ppt
            else: ppt=df_pt
            age_d=[]; gen_d=[]; plat_d=[]
            if len(pga)>0:
                ag_age=pga[pga["age"].isin(AGE_ORDER)].groupby("age").agg(spend=("spend","sum"),leads=("leads","sum")).reset_index()
                ag_age["_o"]=ag_age["age"].apply(lambda x:AGE_ORDER.index(x) if x in AGE_ORDER else 99)
                age_d=seg(ag_age.sort_values("_o"),"age")
                ag_gen=pga[pga["gender"].isin(["female","male"])].groupby("gender").agg(spend=("spend","sum"),leads=("leads","sum")).reset_index().sort_values("leads",ascending=False)
                gen_d=seg(ag_gen,"gender")
            if len(ppt)>0:
                ag_pt=ppt.groupby("platform").agg(spend=("spend","sum"),leads=("leads","sum")).reset_index().sort_values("leads",ascending=False).head(8)
                plat_d=seg(ag_pt,"platform")
            if lname not in result: result[lname]={}
            result[lname][pname]={"age":age_d,"gender":gen_d,"platform":plat_d}

    raw_ga=[]
    if len(df_ga)>0:
        for _,r in df_ga.iterrows():
            if pd.isna(r['date']): continue
            raw_ga.append({'d':r['date'].strftime('%d/%m'),'age':str(r['age']),'gen':str(r['gender']),'sp':round(float(r['spend']),2),'ld':int(r['leads']),'lct':bool(r['is_lct']),'camp':str(r['Campaign Name']) if 'Campaign Name' in r.index else ''})
    raw_pt=[]
    if len(df_pt)>0:
        for _,r in df_pt.iterrows():
            if pd.isna(r['date']): continue
            raw_pt.append({'d':r['date'].strftime('%d/%m'),'plat':str(r['platform']),'sp':round(float(r['spend']),2),'ld':int(r['leads']),'lct':bool(r['is_lct']),'camp':str(r['Campaign Name']) if 'Campaign Name' in r.index else ''})
    result['_raw_ga']=raw_ga; result['_raw_pt']=raw_pt
    return result

# ══ PESQUISA ══════════════════════════════════════════
def load_pesquisa():
    print("  Lendo pesquisa..."); return pd.read_csv(sheet_url("Pesquisa"))

def pesquisa_process(df, total_leads):
    UTM_COLS=["utm_source","utm_medium","utm_campaign","utm_content"]
    SKIP_COLS=set(UTM_COLS+["Carimbo de data/hora","Timestamp","Email","email",
                             "Qual seu e-mail de cadastro no evento?",
                             "Qual seu primeiro nome?","Qual seu whatsapp?",
                             "Nome","nome","ID","id","Unnamed: 0"])
    PERGUNTAS=[c for c in df.columns
               if c not in SKIP_COLS and not c.lower().startswith("unnamed")
               and str(c).strip() and pd.api.types.is_string_dtype(df[c])
               and df[c].nunique()<=50]
    graficos=[]
    for p in PERGUNTAS:
        if p not in df.columns: continue
        vc=df[p].value_counts(); total=vc.sum()
        graficos.append({"pergunta":p,"opcoes":[{"label":str(k),"qtd":int(v),"pct":round(v/total*100,1)} for k,v in vc.items()]})
    filtros={}
    for col in UTM_COLS:
        if col in df.columns:
            filtros[col]=sorted([v for v in df[col].dropna().unique().tolist() if v and str(v)!="nan"])
    rows=[]
    for _,r in df.iterrows():
        row={}
        for p in PERGUNTAS: row[p]=str(r[p]) if p in df.columns and pd.notna(r.get(p)) else None
        for col in UTM_COLS: row[col]=str(r[col]) if col in df.columns and pd.notna(r.get(col)) else None
        rows.append(row)
    return {"total":len(df),"total_leads":int(total_leads),"graficos":graficos,"filtros":filtros,"rows":rows,"perguntas":PERGUNTAS}

# ══ INJEÇÃO ════════════════════════════════════════════
def replace_js_const(html, name, value):
    pattern=rf"const {name}\s*=\s*(?:null|true|false|-?\d[\d\.]*|'[^']*'|\"[^\"]*\"|\{{[\s\S]*?\}}|\[[\s\S]*?\])\s*;"
    replacement=f"const {name} = {json.dumps(value,ensure_ascii=False)};"
    found=[0]
    def do_replace(m): found[0]+=1; return replacement
    new_html=re.sub(pattern,do_replace,html,count=1)
    if not found[0]: print(f"  AVISO: não encontrou const {name}")
    return new_html


# ══ COMPARAÇÃO LP (LPV01 vs LPV02) ════════════════════════
def build_lpv_data(df):
    from collections import defaultdict
    sub = df[df["campaign"].str.contains(LANCAMENTO_COD, na=False)] if LANCAMENTO_COD else df

    lpv_daily = {"LPV01": defaultdict(lambda: defaultdict(float)),
                 "LPV02": defaultdict(lambda: defaultdict(float))}
    lpv_camps = defaultdict(lambda: defaultdict(float))
    camp_lpv  = {}
    all_days_set = set()

    for _, row in sub.iterrows():
        camp = str(row.get("campaign", ""))
        lv   = "LPV01" if "LPV01" in camp else ("LPV02" if "LPV02" in camp else None)
        if lv is None: continue
        d    = row["date"].strftime("%d/%m")
        sp   = float(row.get("spend",       0) or 0)
        imp  = float(row.get("impressions", 0) or 0)
        lc   = float(row.get("link_clicks", 0) or 0)
        pv   = float(row.get("page_view",   0) or 0)
        ld   = float(row.get("leads",       0) or 0)
        all_days_set.add(d); camp_lpv[camp] = lv
        for k,v in [("sp",sp),("imp",imp),("lc",lc),("pv",pv),("ld",ld)]:
            lpv_daily[lv][d][k] += v
            lpv_camps[camp][k]  += v

    def day_key(s):
        dd,mm=s.split("/"); return int(mm)*100+int(dd)
    days = sorted(all_days_set, key=day_key)

    def metrics(agg):
        sp=round(float(agg.get("sp",0)),2); imp=int(agg.get("imp",0))
        lc=int(agg.get("lc",0)); pv=int(agg.get("pv",0)); ld=int(agg.get("ld",0))
        return {"spend":sp,"imp":imp,"lc":lc,"pv":pv,"leads":ld,
                "cpm":  round(sp/imp*1000,2) if imp>0 else None,
                "ctr":  round(lc/imp*100,2)  if imp>0 else None,
                "cr":   round(pv/lc*100,2)   if lc>0  else None,
                "cpl":  round(sp/ld,2)        if ld>0  else None,
                "tx_conv":round(ld/pv*100,2)  if pv>0  else None}

    def build_daily(lv):
        out={"days":days,"spend":[],"imp":[],"lc":[],"pv":[],"leads":[],"cpl":[],"cr":[],"tx_conv":[]}
        for d in days:
            v=lpv_daily[lv][d]
            sp=round(float(v.get("sp",0)),2); imp=int(v.get("imp",0))
            lc=int(v.get("lc",0)); pv=int(v.get("pv",0)); ld=int(v.get("ld",0))
            out["spend"].append(sp); out["imp"].append(imp); out["lc"].append(lc)
            out["pv"].append(pv);   out["leads"].append(ld)
            out["cpl"].append(round(sp/ld,2) if ld>0 else None)
            out["cr"].append(round(pv/lc*100,2) if lc>0 else None)
            out["tx_conv"].append(round(ld/pv*100,2) if pv>0 else None)
        return out

    def totals(lv):
        t=defaultdict(float)
        for d in days:
            for k,v in lpv_daily[lv][d].items(): t[k]+=v
        return t

    return {
        "LPV01":{"totals":metrics(totals("LPV01")),"daily":build_daily("LPV01"),
                 "camps":[{"n":c,**metrics(v)} for c,v in sorted(lpv_camps.items(),key=lambda x:-x[1].get("ld",0)) if camp_lpv.get(c)=="LPV01"]},
        "LPV02":{"totals":metrics(totals("LPV02")),"daily":build_daily("LPV02"),
                 "camps":[{"n":c,**metrics(v)} for c,v in sorted(lpv_camps.items(),key=lambda x:-x[1].get("ld",0)) if camp_lpv.get(c)=="LPV02"]},
        "days": days,
    }

def inject_all(tpl, meta_k, meta_d, meta_dc, meta_raw_c, meta_t, meta_bd, pes, lpv_data=None):
    html=Path(tpl).read_text(encoding="utf-8")
    html=replace_js_const(html,"META_KPIS",       meta_k)
    html=replace_js_const(html,"META_DAILY",       meta_d)
    html=replace_js_const(html,"META_DAILY_CAMPS", meta_dc)
    html=replace_js_const(html,"META_RAW_CAMP",    meta_raw_c)
    html=replace_js_const(html,"META_TABLES",      meta_t)
    html=replace_js_const(html,"META_BD",          meta_bd)
    html=replace_js_const(html,"PESQUISA",         pes if USAR_PESQUISA else False)
    if lpv_data is not None:
        html=replace_js_const(html,"LPV_DATA", lpv_data)
    html=replace_js_const(html,"DATA_GERACAO",     date.today().strftime("%Y-%m-%d"))

    _cpl_bom   = globals().get("CPL_BOM",   globals().get("CPA_BOM",   5.0))
    _cpl_medio = globals().get("CPL_MEDIO", globals().get("CPA_MEDIO", 10.0))

    for k,v in [
        ("LANCAMENTO_COD", f"'{LANCAMENTO_COD}'"),
        ("NOME_CLIENTE",   f"'{NOME_CLIENTE}'"),
        ("LOGO_LETRA",     f"'{LOGO_LETRA}'"),
        ("COR_ACENTO",     f"'{COR_ACENTO}'"),
        # Moeda
        ("MOEDA_SIMBOLO",  f"'{MOEDA_SIMBOLO}'"),
        ("MOEDA_COD",      f"'{MOEDA}'"),
        # Thresholds
        ("CPL_BOM",        str(_cpl_bom)),
        ("CPL_MEDIO",      str(_cpl_medio)),
        ("CTR_BOM",        str(CTR_BOM)),
        ("CTR_MEDIO",      str(CTR_MEDIO)),
        ("CR_BOM",         str(CR_BOM)),
        ("CR_MEDIO",       str(CR_MEDIO)),
        ("TX_CONV_BOM",    str(TX_CONV_BOM)),
        ("TX_CONV_MEDIO",  str(TX_CONV_MEDIO)),
        ("CPM_BOM",        str(CPM_BOM)),
        ("CPM_MEDIO",      str(CPM_MEDIO)),
    ]:
        html=re.sub(rf"const {k}\s*=\s*[^;]+;", f"const {k}={v};", html, count=1)

    html=re.sub(r"\d{2}/\d{2}/\d{4} · via planilha", date.today().strftime("%d/%m/%Y")+" · via planilha", html)
    return html

# ══ MAIN ═══════════════════════════════════════════════
def main():
    print("="*60)
    print(f"Dashboard Lançamento Gratuito — {NOME_CLIENTE} / {LANCAMENTO_COD or 'Todos'}")
    print(f"Moeda: {MOEDA} ({MOEDA_SIMBOLO})")
    print("="*60)
    img_dir=Path("imgs"); img_dir.mkdir(exist_ok=True)

    print("\n[META ADS]")
    df_meta=load_meta()
    m_k=meta_kpis(df_meta)
    m_d=meta_daily(df_meta)
    m_dc=meta_daily_camps(df_meta)
    m_raw=meta_raw(df_meta)
    m_t=meta_tables(df_meta,img_dir)
    m_bd=meta_breakdowns(df_meta)
    total_leads=m_k["lct"]["leads"] if LANCAMENTO_COD else m_k["all"]["leads"]
    print(f"  ✓ {total_leads} leads | {MOEDA_SIMBOLO} {m_k['lct']['spend']:,.2f} invest.")

    print("\n[PESQUISA]")
    if USAR_PESQUISA:
        df_pes=load_pesquisa()
        pes=pesquisa_process(df_pes, total_leads)
        print(f"  ✓ {pes['total']} respostas")
    else:
        pes=None
        print("  (desativada)")

    print("\n[COMPARAÇÃO LP]")
    try:
        lpv_data = build_lpv_data(df_meta)
        l1=lpv_data["LPV01"]["totals"]; l2=lpv_data["LPV02"]["totals"]
        print(f"  LPV01: {l1['leads']} leads | CPL {MOEDA_SIMBOLO}{l1['cpl']} | invest {MOEDA_SIMBOLO}{l1['spend']:.2f}")
        print(f"  LPV02: {l2['leads']} leads | CPL {MOEDA_SIMBOLO}{l2['cpl']} | invest {MOEDA_SIMBOLO}{l2['spend']:.2f}")
    except Exception as e:
        print(f"  ⚠ {e}"); lpv_data = None

    print("\n[HTML]")
    if not Path(TEMPLATE_FILE).exists():
        print(f"  ERRO: {TEMPLATE_FILE} não encontrado"); return
    html=inject_all(TEMPLATE_FILE,m_k,m_d,m_dc,m_raw,m_t,m_bd,pes,lpv_data)
    Path(OUTPUT_FILE).write_text(html,encoding="utf-8")
    print(f"  ✓ {OUTPUT_FILE} ({len(html)//1024}KB)")

    data_json={
        "cliente":NOME_CLIENTE,"cor":COR_ACENTO,"letra":LOGO_LETRA,
        "lancamento":LANCAMENTO_COD,"moeda":MOEDA,"moeda_simbolo":MOEDA_SIMBOLO,
        "atualizado":date.today().strftime("%d/%m/%Y"),
        "kpis":{
            "spend":m_k["lct"].get("spend"),
            "leads":m_k["lct"].get("leads"),
            "cpl":m_k["lct"].get("cpl")
        }
    }
    Path("data.json").write_text(json.dumps(data_json,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"  ✓ data.json\n{'='*60}")

if __name__=="__main__":
    main()
