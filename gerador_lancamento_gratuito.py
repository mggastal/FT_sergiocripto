#!/usr/bin/env python3
"""Gerador Dashboard Lançamento Gratuito v3 — SC
   leads = Action FB Pixel Custom (Offsite Conversion) + Action Omni Purchase
   Multi-lançamento com botões (label, termo_busca)
"""

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

# Lista de lançamentos. Cada item pode ser:
#   "TERMO"             → botão e busca idênticos
#   ("LABEL","TERMO")   → botão mostra LABEL, busca "contém TERMO" no nome da campanha
# Primeiro item = selecionado por padrão ao abrir o dashboard.
LANCAMENTO_CODS  = [
    ("IP03",    "IP03"),
    ("VSL",    "VSL"),
    ("IP01",   "iP01"),
    ("IP02",   "IP02"),
    ("TLC01",  "TLC01"),
    ("TLC02",  "TLC02"),
]
USAR_PESQUISA    = False           # False = oculta aba Pesquisa
USAR_VENDAS      = True            # False = oculta aba Vendas
LPV_LANCAMENTO   = "IP03"         # Lançamento com comparativo de LPs; None = desativa aba

# ══ MOEDA ══════════════════════════════════════════════
# Escolha a moeda do cliente:
#   "BRL"  → R$ (Real Brasileiro)
#   "USD"  → $ (Dólar Americano)
#   "EUR"  → € (Euro)
MOEDA            = "EUR"

# Metas do funil — define cores (verde/amarelo/vermelho)
# ── Foco em VENDAS (VSL): CPV = custo por venda ──
CPV_BOM          = 80.0   # Custo por Venda ≤ este → verde | até CPV_MEDIO → amarelo | acima → vermelho
CPV_MEDIO        = 150.0
CPL_BOM          = 9.06   # (mantido p/ retrocompat, não usado no foco vendas)
CPL_MEDIO        = 12.0
CTR_BOM          = 1.0    # CTR ≥ 1.2% → verde | 0.8-1.2% → amarelo | abaixo → vermelho
CTR_MEDIO        = 0.8
CR_BOM           = 65.0   # Connect Rate ≥ 40% → verde | 25-40% → amarelo | abaixo → vermelho
CR_MEDIO         = 60.0
TX_CONV_BOM      = 25.0   # (retrocompat)
TX_CONV_MEDIO    = 18.0
# Funil VSL:
CHECKOUT_BOM     = 8.0    # Taxa de Checkout (checkout/LPView) ≥ → verde
CHECKOUT_MEDIO   = 4.0
TXLP_BOM         = 3.0    # Taxa de Conversão LP (compra/LPView) ≥ → verde
TXLP_MEDIO       = 1.5
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

# Normaliza LANCAMENTO_CODS → _LCT_PAIRS (label, termo) e LANCAMENTO_CODS → só labels
def _norm(item):
    if isinstance(item,(tuple,list)) and len(item)==2:
        return (str(item[0]).strip(), str(item[1]).strip())
    return (str(item).strip(), str(item).strip())
_LCT_PAIRS   = [_norm(c) for c in LANCAMENTO_CODS if c and (c[0] if isinstance(c,(tuple,list)) else c)]
_LCT_PAIRS   = [(lb,tr) for lb,tr in _LCT_PAIRS if lb and tr]
LANCAMENTO_CODS = [lb for lb,_ in _LCT_PAIRS]
_LCT_TERMO_POR_LABEL = {lb:tr for lb,tr in _LCT_PAIRS}

def matched_codes(campaign_name):
    """Retorna labels cujo termo aparece no nome da campanha."""
    if not _LCT_PAIRS: return []
    name = str(campaign_name).lower()
    return [lb for lb,tr in _LCT_PAIRS if tr.lower() in name]

def filter_groups():
    return list(LANCAMENTO_CODS) + ["all"]

# ══════════════════════════════════════════════════════
def sheet_url(t): return f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={t}"
URL_META = sheet_url("meta-ads")
URL_PES  = sheet_url("Pesquisa")
URL_GA   = sheet_url("breakdown-gender-age")
URL_PT   = sheet_url("breakdown-platform")
ABA_VENDAS = "Vendas VSL"          # aba da planilha com as vendas
MOSTRAR_VENDAS = False       # True para exibir a página/menu "Vendas" quando as vendas começarem
DATA_MINIMA = "01/01/2026"   # ignora linhas ANTES desta data. A planilha tem histórico desde set/2025;
                             # como o dashboard usa datas dd/mm, a partir de 22/09/2026 os dias de 2025
                             # colidiriam com os de 2026 e inflariam os filtros (mesmo bug já visto na Rafa).
URL_VENDAS = sheet_url(ABA_VENDAS)

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
        "Action FB Pixel Custom (Offsite Conversion)":"leads_pixel",
        "Action Leads":"leads_native",
        "Action Omni Initiated Checkout":"checkout",
        "Action Omni Purchase":"purchases",
        "Action Value Omni Purchase":"purchase_value"
    })
    df["date"]=pd.to_datetime(df["date"],errors="coerce")
    df=df.dropna(subset=["date"])
    if DATA_MINIMA:
        _lim=pd.to_datetime(DATA_MINIMA,dayfirst=True)
        _antes=int((df["date"]<_lim).sum())
        if _antes:
            df=df[df["date"]>=_lim]
            print(f"     ⚠ {_antes} linha(s) antes de {DATA_MINIMA} ignorada(s)")
    for c in ["spend","impressions","link_clicks","page_view","leads_pixel","leads_native","checkout","purchases","purchase_value"]:
        if c not in df.columns: df[c]=0
        df[c]=to_num(df[c])
    # leads = Action FB Pixel Custom + Action Omni Purchase (purchase configurado como lead tbm)
    # leads = soma de todas as métricas de lead/conversão (cada lançamento usa uma diferente)
    df["leads"] = df["leads_pixel"] + df["leads_native"] + df["purchases"]
    if "status" in df.columns:
        df["status"]=df["status"].astype(str).str.strip().str.upper()
    df["lct_codes"]=df["campaign"].apply(matched_codes)
    df=df.dropna(subset=["date"])
    print(f"     {len(df)} linhas | {df['date'].min().date()} → {df['date'].max().date()}")
    return df

def calc_kpis(p):
    sp=float(p["spend"].sum()); imp=float(p["impressions"].sum())
    lc=float(p["link_clicks"].sum()); pv=float(p["page_view"].sum())
    ld=float(p["leads"].sum())
    ck=float(p["checkout"].sum()) if "checkout" in p.columns else 0.0
    pu=float(p["purchases"].sum()) if "purchases" in p.columns else 0.0
    pval=float(p["purchase_value"].sum()) if "purchase_value" in p.columns else 0.0
    return {
        "spend":round(sp,2),"impressions":int(imp),"link_clicks":int(lc),
        "page_view":int(pv),"leads":int(ld),
        "checkout":int(ck),"purchases":int(pu),"purchase_value":round(pval,2),
        "ctr":   round(lc/imp*100,2) if imp>0 else None,
        "connect_rate":round(pv/lc*100,2) if lc>0 else None,
        "tx_conv":round(ld/pv*100,2) if pv>0 else None,
        "cpl":   round(sp/ld,2) if ld>0 else None,
        "cpm":   round(sp/imp*1000,2) if imp>0 else None,
        "tx_checkout":round(ck/pv*100,2) if pv>0 else None,
        "tx_conv_lp": round(pu/pv*100,2) if pv>0 else None,
        "cpv":       round(sp/pu,2) if pu>0 else None
    }

def calc_temp(p):
    """Calcula métricas por temperatura de público: TT=quente, TF=frio."""
    def t_kpi(sub):
        sp = float(sub["spend"].sum()); ld = float(sub["leads"].sum())
        return {"spend": round(sp,2), "leads": int(ld), "cpl": round(sp/ld,2) if ld>0 else None}
    q = p[p["campaign"].str.contains("-TT-", na=False)]
    f = p[p["campaign"].str.contains("-TF-", na=False)]
    return {"quente": t_kpi(q), "frio": t_kpi(f)}

def meta_kpis(df):
    result = {}
    for g in filter_groups():
        sub = df[df["lct_codes"].apply(lambda c: g in c)] if g!="all" else df
        kpis = calc_kpis(sub)
        kpis["temp"] = calc_temp(sub)
        result[g] = kpis
    return result

def build_daily(p):
    agg=p.groupby("date").agg(
        spend=("spend","sum"),impressions=("impressions","sum"),
        link_clicks=("link_clicks","sum"),page_view=("page_view","sum"),
        leads=("leads","sum"),checkout=("checkout","sum"),
        purchases=("purchases","sum"),purchase_value=("purchase_value","sum")
    ).reset_index().sort_values("date")
    out={k:[] for k in ["days","spend","impressions","link_clicks","page_view","leads",
        "checkout","purchases","purchase_value","ctr","connect_rate","tx_conv","cpl","cpm",
        "tx_checkout","tx_conv_lp","cpv","receita"]}
    for _,r in agg.iterrows():
        sp=float(r["spend"]); imp=float(r["impressions"]); lc=float(r["link_clicks"])
        pv=float(r["page_view"]); ld=float(r["leads"])
        ck=float(r["checkout"]); pu=float(r["purchases"]); pval=float(r["purchase_value"])
        out["days"].append(r["date"].strftime("%d/%m/%y"))
        out["spend"].append(round(sp,2)); out["impressions"].append(int(imp))
        out["link_clicks"].append(int(lc)); out["page_view"].append(int(pv))
        out["leads"].append(int(ld)); out["checkout"].append(int(ck))
        out["purchases"].append(int(pu)); out["purchase_value"].append(round(pval,2))
        out["ctr"].append(round(lc/imp*100,2) if imp>0 else None)
        out["connect_rate"].append(round(pv/lc*100,2) if lc>0 else None)
        out["tx_conv"].append(round(ld/pv*100,2) if pv>0 else None)
        out["cpl"].append(round(sp/ld,2) if ld>0 else None)
        out["cpm"].append(round(sp/imp*1000,2) if imp>0 else None)
        # ── Funil VSL ──
        out["tx_checkout"].append(round(ck/pv*100,2) if pv>0 else None)  # checkout / LPView
        out["tx_conv_lp"].append(round(pu/pv*100,2) if pv>0 else None)   # compra / LPView
        out["cpv"].append(round(sp/pu,2) if pu>0 else None)              # custo por venda
        out["receita"].append(round(pval,2))
    return out

def subset_for_group(df, g):
    return df if g=="all" else df[df["lct_codes"].apply(lambda c: g in c)]

def meta_daily(df):
    return {g: build_daily(subset_for_group(df, g)) for g in filter_groups()}

def meta_daily_camps(df):
    result={}
    for g in filter_groups():
        subset=subset_for_group(df,g)
        result[g]={camp: build_daily(subset[subset["campaign"]==camp]) for camp in subset["campaign"].unique()}
    return result

def meta_raw(df):
    rows=[]
    agg=df.groupby(["date","campaign","adset"]).agg(
        spend=("spend","sum"),leads=("leads","sum"),
        impressions=("impressions","sum"),link_clicks=("link_clicks","sum"),
        page_view=("page_view","sum")
    ).reset_index()
    codes_map=df.groupby(["date","campaign","adset"])["lct_codes"].first()
    for _,r in agg.iterrows():
        key=(r["date"],r["campaign"],r["adset"])
        codes=codes_map.get(key,[])
        rows.append({
            "d":r["date"].strftime("%d/%m/%y"),"c":str(r["campaign"]),"a":str(r["adset"]),
            "codes":codes,"sp":round(float(r["spend"]),2),
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
    def ag(sub,cols): return sub.groupby(cols).agg(spend=("spend","sum"),impressions=("impressions","sum"),link_clicks=("link_clicks","sum"),page_view=("page_view","sum"),leads=("leads","sum"),checkout=("checkout","sum"),purchases=("purchases","sum"),purchase_value=("purchase_value","sum")).reset_index()

    def calc_row(r):
        sp=round(float(r["spend"]),2); imp=int(r["impressions"]); lc=int(r["link_clicks"])
        pv=int(r["page_view"]); ld=int(r["leads"])
        ck=int(r["checkout"]) if "checkout" in r else 0
        pu=int(r["purchases"]) if "purchases" in r else 0
        pval=round(float(r["purchase_value"]),2) if "purchase_value" in r else 0.0
        return {"spend":sp,"imp":imp,"lc":lc,"pv":pv,"ld":ld,
            "checkout":ck,"purchases":pu,"receita":pval,
            "ctr":round(lc/imp*100,2) if imp>0 else None,
            "cr":round(pv/lc*100,2) if lc>0 else None,
            "tx_cv":round(ld/pv*100,2) if pv>0 else None,
            "tx_checkout":round(ck/pv*100,2) if pv>0 else None,
            "tx_conv_lp":round(pu/pv*100,2) if pv>0 else None,
            "cpl":round(sp/ld,2) if ld>0 else None,
            "cpv":round(sp/pu,2) if pu>0 else None,
            "roas":round(pval/sp,2) if sp>0 else None,
            "cpm":round(sp/imp*1000,2) if imp>0 else None}

    camps_agg=ag(p,"campaign")
    camps=[{"n":str(r["campaign"]),"status":camp_status.get(str(r["campaign"]),""),**calc_row(r)} for _,r in camps_agg.sort_values(["purchases","leads"],ascending=False).iterrows()]

    adsets_agg=ag(p,["campaign","adset"])
    adsets=[{"n":str(r["adset"]),"camp":str(r["campaign"]),
             "status":adset_status.get((str(r["campaign"]),str(r["adset"])),""),
             **calc_row(r)} for _,r in adsets_agg.sort_values(["purchases","leads"],ascending=False).iterrows()]

    df_full_thumb=df[df["thumb"].notna()&(df["thumb"].astype(str)!="nan")] if "thumb" in df.columns else pd.DataFrame()
    thumb_map={}
    for _,r in df_full_thumb.iterrows():
        k=(str(r["ad"]),str(r["adset"]),str(r["campaign"]))
        if k not in thumb_map: thumb_map[k]=download_thumb(str(r["thumb"]),img_dir)

    ads_agg=p.groupby(["ad","adset","campaign"]).agg(spend=("spend","sum"),impressions=("impressions","sum"),link_clicks=("link_clicks","sum"),page_view=("page_view","sum"),leads=("leads","sum"),checkout=("checkout","sum"),purchases=("purchases","sum"),purchase_value=("purchase_value","sum")).reset_index().sort_values(["purchases","leads"],ascending=False)
    ads=[]
    for _,r in ads_agg.iterrows():
        sp=round(float(r["spend"]),2); imp=int(r["impressions"]); lc=int(r["link_clicks"])
        pv=int(r["page_view"]); ld=int(r["leads"])
        ck=int(r["checkout"]); pu=int(r["purchases"]); pval=round(float(r["purchase_value"]),2)
        k=(str(r["ad"]),str(r["adset"]),str(r["campaign"]))
        ads.append({"n":str(r["ad"]),"adset":str(r["adset"]),"camp":str(r["campaign"]),
            "status":ad_status.get((str(r["campaign"]),str(r["adset"]),str(r["ad"])),""),
            "thumb":thumb_map.get(k,""),"spend":sp,"imp":imp,"lc":lc,"pv":pv,"ld":ld,
            "checkout":ck,"purchases":pu,"receita":pval,
            "ctr":round(lc/imp*100,2) if imp>0 else None,
            "cr":round(pv/lc*100,2) if lc>0 else None,
            "tx_checkout":round(ck/pv*100,2) if pv>0 else None,
            "tx_conv_lp":round(pu/pv*100,2) if pv>0 else None,
            "cpv":round(sp/pu,2) if pu>0 else None,
            "roas":round(pval/sp,2) if sp>0 else None,
            "cpl":round(sp/ld,2) if ld>0 else None})
    return {"camps":camps,"adsets":adsets,"ads":ads}

def meta_tables(df, img_dir):
    hoje=pd.Timestamp(date.today())
    camp_status, adset_status, ad_status = build_status_maps(df)
    result={}
    for g in filter_groups():
        subset=subset_for_group(df,g)
        result[g]={}
        for pname,n in [("1",1),("7",7),("14",14),("30",30),("all",0)]:
            p=subset[subset["date"]>=hoje-pd.Timedelta(days=n-1)] if n>0 else subset
            result[g][pname]=meta_tables_period(df,p,img_dir,camp_status,adset_status,ad_status)
            print(f"     [{g}][{pname}]: {len(result[g][pname]['camps'])} camps | {len(result[g][pname]['ads'])} ads")
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
        # soma todas as métricas de lead disponíveis no breakdown
        leads_ga = pd.Series([0.0]*len(df_ga))
        for _lc in ["Action FB Pixel Custom (Offsite Conversion)","Action Leads","Action Omni Purchase"]:
            if _lc in df_ga.columns: leads_ga = leads_ga + to_num(df_ga[_lc])
        df_ga["leads"] = leads_ga
        df_ga["age"]=df_ga["Age (Breakdown)"].astype(str)
        df_ga["gender"]=df_ga["Gender (Breakdown)"].astype(str)
        if "Campaign Name" in df_ga.columns:
            df_ga["lct_codes"]=df_ga["Campaign Name"].apply(matched_codes)
        else:
            df_ga["lct_codes"]=[[] for _ in range(len(df_ga))]
        df_ga=df_ga.dropna(subset=["date"])
    except Exception as e: print(f"  Aviso GA: {e}"); df_ga=pd.DataFrame()
    try:
        df_pt=pd.read_csv(URL_PT)
        df_pt["date"]=pd.to_datetime(df_pt["Date"],errors="coerce")
        df_pt["spend"]=to_num(df_pt["Spend (Cost, Amount Spent)"])
        leads_pt = pd.Series([0.0]*len(df_pt))
        for _lc in ["Action FB Pixel Custom (Offsite Conversion)","Action Leads","Action Omni Purchase"]:
            if _lc in df_pt.columns: leads_pt = leads_pt + to_num(df_pt[_lc])
        df_pt["leads"] = leads_pt
        df_pt["platform"]=df_pt["Platform Position (Breakdown)"].astype(str)
        if "Campaign Name" in df_pt.columns:
            df_pt["lct_codes"]=df_pt["Campaign Name"].apply(matched_codes)
        else:
            df_pt["lct_codes"]=[[] for _ in range(len(df_pt))]
        df_pt=df_pt.dropna(subset=["date"])
    except Exception as e: print(f"  Aviso PT: {e}"); df_pt=pd.DataFrame()

    result={}
    for pname,n in [("1",1),("7",7),("14",14),("30",30),("all",0)]:
        start=hoje_bd-pd.Timedelta(days=n-1) if n>0 else None
        for g in filter_groups():
            if len(df_ga)>0:
                pga=df_ga if g=="all" else df_ga[df_ga["lct_codes"].apply(lambda c: g in c)]
                pga=pga[(pga["date"]>=start)&(pga["date"]<=hoje_bd)] if n>0 else pga
            else: pga=df_ga
            if len(df_pt)>0:
                ppt=df_pt if g=="all" else df_pt[df_pt["lct_codes"].apply(lambda c: g in c)]
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
            if g not in result: result[g]={}
            result[g][pname]={"age":age_d,"gender":gen_d,"platform":plat_d}

    raw_ga=[]
    if len(df_ga)>0:
        for _,r in df_ga.iterrows():
            if pd.isna(r['date']): continue
            raw_ga.append({'d':r['date'].strftime('%d/%m/%y'),'age':str(r['age']),'gen':str(r['gender']),'sp':round(float(r['spend']),2),'ld':int(r['leads']),'codes':r['lct_codes'],'camp':str(r['Campaign Name']) if 'Campaign Name' in r.index else ''})
    raw_pt=[]
    if len(df_pt)>0:
        for _,r in df_pt.iterrows():
            if pd.isna(r['date']): continue
            raw_pt.append({'d':r['date'].strftime('%d/%m/%y'),'plat':str(r['platform']),'sp':round(float(r['spend']),2),'ld':int(r['leads']),'codes':r['lct_codes'],'camp':str(r['Campaign Name']) if 'Campaign Name' in r.index else ''})
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
    # Palavras que indicam campo de identificação livre (não é pergunta de múltipla escolha)
    _ID_HINTS=("nome","name","email","e-mail","mail","whats","telefone","phone",
               "celular","cpf","data","hora","carimbo","timestamp","marca temporal",
               "marca de tiempo","fecha","sello")
    def _is_pergunta(c):
        if c in SKIP_COLS or c.lower().startswith("unnamed"): return False
        if not str(c).strip(): return False
        cl=str(c).lower()
        if any(h in cl for h in _ID_HINTS): return False
        if not pd.api.types.is_string_dtype(df[c]): return False
        serie=df[c].dropna()
        n=len(serie)
        if n==0: return False
        nun=serie.nunique()
        if nun>50: return False
        # descarta perguntas "abertas": quando a maioria das respostas é única
        # (nome, e-mail, etc. que escaparam das dicas acima). Limiar: >60% únicas
        # e com pelo menos 8 respostas para evitar falso-positivo em amostras pequenas.
        if n>=8 and (nun/n)>0.6: return False
        return True
    PERGUNTAS=[c for c in df.columns if _is_pergunta(c)]
    def _clean_q(s): return " ".join(str(s).split())  # remove \n e espaços duplos
    graficos=[]  # reconstruído após filtrar rows vazias
    EMPTY_TOKEN="(vazio)"
    # Normaliza UTMs: valor real (str) ou EMPTY_TOKEN quando ausente/vazio.
    # Assim TODAS as respostas entram nos filtros e "tudo marcado" = 100% dos dados.
    def _utm_val(r, col):
        if col not in df.columns: return EMPTY_TOKEN
        v = r.get(col)
        if pd.isna(v): return EMPTY_TOKEN
        s = str(v).strip()
        return s if s and s.lower()!="nan" else EMPTY_TOKEN
    rows=[]
    for _,r in df.iterrows():
        row={}
        _tem_resposta=False
        for p in PERGUNTAS:
            val=str(r[p]) if p in df.columns and pd.notna(r.get(p)) else None
            row[p]=val
            if val and val.strip(): _tem_resposta=True
        for col in UTM_COLS: row[col]=_utm_val(r, col)
        # descarta linhas totalmente vazias (planilha às vezes traz milhares de linhas em branco)
        if _tem_resposta: rows.append(row)
    # gráficos a partir das rows válidas (não do df cru com linhas vazias)
    from collections import Counter as _Counter
    for p in PERGUNTAS:
        _c=_Counter(row[p] for row in rows if row.get(p) and str(row[p]).strip())
        _tot=sum(_c.values())
        if _tot==0: continue
        graficos.append({"pergunta":p,"opcoes":[{"label":str(k),"qtd":int(v),"pct":round(v/_tot*100,1)} for k,v in _c.most_common()]})
    # Filtros a partir dos valores efetivamente presentes nas rows (inclui EMPTY_TOKEN);
    # ordena com valores reais primeiro e "(vazio)" por último.
    filtros={}
    for col in UTM_COLS:
        vals=sorted(set(row[col] for row in rows if row.get(col) and row[col]!=EMPTY_TOKEN))
        if any(row.get(col)==EMPTY_TOKEN for row in rows): vals=vals+[EMPTY_TOKEN]
        if vals: filtros[col]=vals
    # Série de respostas por dia (para o gráfico no topo, adaptável ao período)
    resp_por_dia=[]
    _date_col=None
    for c in df.columns:
        cl=str(c).lower()
        if any(h in cl for h in ("carimbo","timestamp","marca temporal","marca de tiempo","data/hora","fecha","sello de tiempo")):
            _date_col=c; break
    if _date_col is not None:
        _dt=pd.to_datetime(df[_date_col], errors="coerce", dayfirst=True)
        _por_dia=_dt.dropna().dt.strftime("%d/%m/%y").value_counts()
        def _dk(s):
            dd,mm=s.split("/"); return int(mm)*100+int(dd)
        for d in sorted(_por_dia.index, key=_dk):
            resp_por_dia.append({"d":d,"n":int(_por_dia[d])})
        # rows recebem a data para permitir filtro por período no front
        _dt_fmt=_dt.dt.strftime("%d/%m/%y")
        for i,(_,r) in enumerate(df.iterrows()):
            if i<len(rows):
                v=_dt_fmt.iloc[i] if i<len(_dt_fmt) else None
                rows[i]["_d"]=v if pd.notna(v) else None
    return {"total":len(rows),"total_leads":int(total_leads),"graficos":graficos,
            "filtros":filtros,"rows":rows,"perguntas":PERGUNTAS,"resp_por_dia":resp_por_dia}

# ══ INJEÇÃO ════════════════════════════════════════════

# ══════════════════════════════════════════════════════
# VENDAS
# ══════════════════════════════════════════════════════
def load_vendas():
    print("  Lendo Vendas...")
    df = pd.read_csv(URL_VENDAS)
    df = df.rename(columns={
        "Precio Total (Euros)": "valor", "Precio Total": "valor", "Valor": "valor",
        "Data": "data", "Fecha": "data",
        "Campanha": "campanha", "Campaña": "campanha",
        "Conjunto": "conjunto", "Criativo": "criativo",
        "Pagamento": "pagamento", "Pago": "pagamento",
        "País": "pais", "Pais": "pais", "Email": "email",
    })
    df["valor"] = to_num(df["valor"]) if "valor" in df.columns else 0
    df["data"]  = pd.to_datetime(df.get("data"), errors="coerce", dayfirst=True)
    for c in ["campanha", "conjunto", "criativo", "pagamento", "pais", "email"]:
        if c not in df.columns: df[c] = None
    # descarta linhas totalmente vazias (planilha traz milhares de linhas em branco)
    df = df[(df["valor"] > 0) | df["email"].notna()]
    print(f"     {len(df)} vendas")
    return df


def build_vendas_data(df_v, df_meta):
    """Cruza vendas com investimento. Receita TOTAL entra no ROAS do lançamento
    (a UTM do CRM não sobrescreve: comprador antigo carrega UTM de lançamento
    anterior ou vazia, mas a venda é deste lançamento)."""
    import re as _re
    from collections import defaultdict

    df_v = df_v.copy()
    for c in ["campanha", "conjunto", "criativo", "pagamento", "pais"]:
        df_v[c] = df_v[c].fillna("").astype(str).str.strip()

    # ── Investimento do lançamento, por nível ──
    _lct_f = LANCAMENTO_CODS[0] if LANCAMENTO_CODS else None
    m = df_meta[df_meta["lct_codes"].apply(lambda c: _lct_f in c)] if _lct_f else df_meta
    inv_total = float(m["spend"].sum())
    inv_camp  = m.groupby("campaign")["spend"].sum().to_dict()
    inv_conj  = m.groupby("adset")["spend"].sum().to_dict()
    inv_criat = m.groupby("ad")["spend"].sum().to_dict()
    inv_lpv   = defaultdict(float)
    for _, r in m.iterrows():
        mm = _re.search(r"LPV(\d+)", str(r.get("campaign", "")))
        if mm: inv_lpv["LPV" + mm.group(1)] += float(r.get("spend", 0) or 0)

    def r2(v): return round(float(v), 2)
    def roas(rec, inv): return r2(rec / inv) if inv and inv > 0 else None

    # ── Totais ──
    receita = float(df_v["valor"].sum())
    n_vendas = int(len(df_v))
    _termo_f = _LCT_TERMO_POR_LABEL.get(_lct_f, _lct_f) if _lct_f else None
    atrib   = df_v[df_v["campanha"].str.contains(_termo_f, na=False, case=False)] if _termo_f else df_v
    outras  = df_v.drop(atrib.index)

    totals = {
        "receita": r2(receita), "vendas": n_vendas,
        "ticket": r2(receita / n_vendas) if n_vendas else None,
        "invest": r2(inv_total), "roas": roas(receita, inv_total),
        "cac": r2(inv_total / n_vendas) if n_vendas else None,
        "receita_atrib": r2(atrib["valor"].sum()), "vendas_atrib": int(len(atrib)),
        "receita_outras": r2(outras["valor"].sum()), "vendas_outras": int(len(outras)),
        "roas_atrib": roas(float(atrib["valor"].sum()), inv_total),
    }

    # ── Série diária ──
    dias = sorted(df_v["data"].dropna().dt.strftime("%d/%m/%y").unique(),
                  key=lambda s: tuple(int(x) for x in reversed(s.split("/"))))
    g = df_v.dropna(subset=["data"]).groupby(df_v["data"].dt.strftime("%d/%m/%y"))
    daily = {"days": dias,
             "receita": [r2(g.get_group(d)["valor"].sum()) if d in g.groups else 0 for d in dias],
             "vendas":  [int(len(g.get_group(d))) if d in g.groups else 0 for d in dias]}
    # investimento por dia (do meta) — para ROAS diário quando houver sobreposição
    mg = m.groupby(m["date"].dt.strftime("%d/%m/%y"))["spend"].sum().to_dict()
    daily["invest"] = [r2(mg.get(d, 0)) for d in dias]

    # ── Quebras (só vendas com UTM deste lançamento cruzam com investimento) ──
    def quebra(col, inv_map, inv_ref=None):
        out = []
        sub = atrib[atrib[col] != ""]
        for nome, grp in sub.groupby(col):
            rec = float(grp["valor"].sum()); inv = float(inv_map.get(nome, 0))
            out.append({"n": nome, "vendas": int(len(grp)), "receita": r2(rec),
                        "invest": r2(inv), "roas": roas(rec, inv),
                        "ticket": r2(rec / len(grp)) if len(grp) else None})
        out = sorted(out, key=lambda x: -x["receita"])
        # investimento que não gerou venda neste nível → linha agregada,
        # para o TOTAL da tabela bater com o investimento real do lançamento
        base = inv_ref if inv_ref is not None else sum(inv_map.values())
        resto = base - sum(x["invest"] for x in out)
        if resto > 0.01:
            out.append({"n": "__SEM_VENDA__", "vendas": 0, "receita": 0.0,
                        "invest": r2(resto), "roas": 0.0, "ticket": None})
        return out

    camps     = quebra("campanha", inv_camp, inv_total)
    publicos  = quebra("conjunto", inv_conj, inv_total)
    criativos = quebra("criativo", inv_criat, inv_total)

    # LPs: agrega por LPVxx
    lp_rec = defaultdict(float); lp_n = defaultdict(int)
    for _, r in atrib.iterrows():
        mm = _re.search(r"LPV(\d+)", r["campanha"])
        if not mm: continue
        k = "LPV" + mm.group(1)
        lp_rec[k] += float(r["valor"] or 0); lp_n[k] += 1
    lps = []
    for k in sorted(set(list(lp_rec.keys()) + list(inv_lpv.keys())),
                    key=lambda x: int(x.replace("LPV", ""))):
        rec = lp_rec.get(k, 0.0); inv = inv_lpv.get(k, 0.0)
        lps.append({"n": k, "vendas": lp_n.get(k, 0), "receita": r2(rec),
                    "invest": r2(inv), "roas": roas(rec, inv),
                    "ticket": r2(rec / lp_n[k]) if lp_n.get(k) else None})
    _resto_lp = inv_total - sum(x["invest"] for x in lps)
    if _resto_lp > 0.01:
        lps.append({"n": "__SEM_VENDA__", "vendas": 0, "receita": 0.0,
                    "invest": r2(_resto_lp), "roas": 0.0, "ticket": None})

    # ── Simples (sem investimento) ──
    def simples(col, src):
        out = []
        s = src.copy()
        s[col] = s[col].replace("", "__SEM_REG__")
        for nome, grp in s.groupby(col):
            out.append({"n": nome, "vendas": int(len(grp)), "receita": r2(grp["valor"].sum())})
        return sorted(out, key=lambda x: -x["receita"])

    pagamentos = simples("pagamento", df_v)
    paises     = simples("pais", df_v)

    # Outras origens: agrupa por campanha (vazio → "Sem campanha")
    o = outras.copy()
    o["origem"] = o["campanha"].replace("", "__SEM__")
    outras_lst = []
    for nome, grp in o.groupby("origem"):
        outras_lst.append({"n": "(sem campanha)" if nome == "__SEM__" else nome,
                           "vendas": int(len(grp)), "receita": r2(grp["valor"].sum())})
    outras_lst = sorted(outras_lst, key=lambda x: -x["receita"])

    return {"totals": totals, "daily": daily, "camps": camps, "publicos": publicos,
            "criativos": criativos, "lps": lps, "pagamentos": pagamentos,
            "paises": paises, "outras": outras_lst}


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
    import re as _re
    from collections import defaultdict
    # Usa LPV_LANCAMENTO se definido, senão primeiro da lista
    _lct_filter = globals().get("LPV_LANCAMENTO") or (LANCAMENTO_CODS[0] if LANCAMENTO_CODS else None)
    sub = df[df["lct_codes"].apply(lambda c: _lct_filter in c)] if _lct_filter else df

    lpv_daily = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    lpv_camps = defaultdict(lambda: defaultdict(float))
    camp_lpv  = {}
    all_days_set = set()
    lpv_seen  = set()

    def detect_lpv(camp):
        m = _re.search(r"LPV(\d+)", camp)
        return ("LPV" + m.group(1)) if m else None

    for _, row in sub.iterrows():
        camp = str(row.get("campaign", ""))
        lv   = detect_lpv(camp)
        if lv is None: continue
        d    = row["date"].strftime("%d/%m/%y")
        sp   = float(row.get("spend",       0) or 0)
        imp  = float(row.get("impressions", 0) or 0)
        lc   = float(row.get("link_clicks", 0) or 0)
        pv   = float(row.get("page_view",   0) or 0)
        ld   = float(row.get("leads",       0) or 0)
        ck   = float(row.get("checkout",    0) or 0)
        pu   = float(row.get("purchases",   0) or 0)
        pval = float(row.get("purchase_value",0) or 0)
        all_days_set.add(d); camp_lpv[camp] = lv; lpv_seen.add(lv)
        for k,v in [("sp",sp),("imp",imp),("lc",lc),("pv",pv),("ld",ld),("ck",ck),("pu",pu),("pval",pval)]:
            lpv_daily[lv][d][k] += v
            lpv_camps[camp][k]  += v

    def day_key(s):
        parts=s.split("/"); dd=parts[0]; mm=parts[1]; yy=int(parts[2]) if len(parts)>2 else 0
        return yy*10000+int(mm)*100+int(dd)
    days = sorted(all_days_set, key=day_key)
    # ordena LPV01, LPV02, LPV03... numericamente
    lpv_list = sorted(lpv_seen, key=lambda x: int(x.replace("LPV","")))

    def metrics(agg):
        sp=round(float(agg.get("sp",0)),2); imp=int(agg.get("imp",0))
        lc=int(agg.get("lc",0)); pv=int(agg.get("pv",0)); ld=int(agg.get("ld",0))
        ck=int(agg.get("ck",0)); pu=int(agg.get("pu",0)); pval=round(float(agg.get("pval",0)),2)
        return {"spend":sp,"imp":imp,"lc":lc,"pv":pv,"leads":ld,
                "checkout":ck,"purchases":pu,"receita":pval,
                "cpm":  round(sp/imp*1000,2) if imp>0 else None,
                "ctr":  round(lc/imp*100,2)  if imp>0 else None,
                "cr":   round(pv/lc*100,2)   if lc>0  else None,
                "cpl":  round(sp/ld,2)        if ld>0  else None,
                "cpv":  round(sp/pu,2)        if pu>0  else None,
                "tx_checkout":round(ck/pv*100,2) if pv>0 else None,
                "tx_conv_lp": round(pu/pv*100,2)  if pv>0 else None,
                "roas": round(pval/sp,2)      if sp>0  else None,
                "tx_conv":round(ld/pv*100,2)  if pv>0  else None}

    def build_daily(lv):
        out={"days":days,"spend":[],"imp":[],"lc":[],"pv":[],"leads":[],"checkout":[],"purchases":[],"receita":[],
             "cpl":[],"cpv":[],"cr":[],"tx_checkout":[],"tx_conv_lp":[],"tx_conv":[]}
        for d in days:
            v=lpv_daily[lv][d]
            sp=round(float(v.get("sp",0)),2); imp=int(v.get("imp",0))
            lc=int(v.get("lc",0)); pv=int(v.get("pv",0)); ld=int(v.get("ld",0))
            ck=int(v.get("ck",0)); pu=int(v.get("pu",0)); pval=round(float(v.get("pval",0)),2)
            out["spend"].append(sp); out["imp"].append(imp); out["lc"].append(lc)
            out["pv"].append(pv);   out["leads"].append(ld)
            out["checkout"].append(ck); out["purchases"].append(pu)
            out["receita"].append(pval)
            out["cpl"].append(round(sp/ld,2) if ld>0 else None)
            out["cpv"].append(round(sp/pu,2) if pu>0 else None)
            out["tx_checkout"].append(round(ck/pv*100,2) if pv>0 else None)
            out["tx_conv_lp"].append(round(pu/pv*100,2) if pv>0 else None)
            out["cr"].append(round(pv/lc*100,2) if lc>0 else None)
            out["tx_conv"].append(round(ld/pv*100,2) if pv>0 else None)
        return out

    def totals(lv):
        t=defaultdict(float)
        for d in days:
            for k,v in lpv_daily[lv][d].items(): t[k]+=v
        return t

    result = {"days": days, "order": lpv_list}
    for lv in lpv_list:
        result[lv] = {
            "totals": metrics(totals(lv)),
            "daily":  build_daily(lv),
            "camps":  [{"n":c, **metrics(v)} for c,v in sorted(lpv_camps.items(), key=lambda x:-x[1].get("ld",0)) if camp_lpv.get(c)==lv],
        }
    return result


def inject_all(tpl, meta_k, meta_d, meta_dc, meta_raw_c, meta_t, meta_bd, pes, lpv_data=None, vendas_data=None):
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
        # LPV_MODO: 'leads' para lançamentos de captação, 'vendas' para VSL/venda direta
        _lpv_modo = "leads"  # IP03 é captação
        html=re.sub(r"const LPV_MODO\s*=\s*[^;]+;", f"const LPV_MODO='{_lpv_modo}';", html, count=1)
    html=replace_js_const(html,"VENDAS_DATA", vendas_data if (USAR_VENDAS and vendas_data) else False)
    html=replace_js_const(html,"LANCAMENTO_CODS",  LANCAMENTO_CODS)
    html=replace_js_const(html,"MOSTRAR_VENDAS",  MOSTRAR_VENDAS)
    html=replace_js_const(html,"DATA_GERACAO",     date.today().strftime("%Y-%m-%d"))

    _cpl_bom   = globals().get("CPL_BOM",   globals().get("CPA_BOM",   5.0))
    _cpl_medio = globals().get("CPL_MEDIO", globals().get("CPA_MEDIO", 10.0))

    for k,v in [
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
        # Funil VSL (vendas)
        ("CPV_BOM",        str(CPV_BOM)),
        ("CPV_MEDIO",      str(CPV_MEDIO)),
        ("CHECKOUT_BOM",   str(CHECKOUT_BOM)),
        ("CHECKOUT_MEDIO", str(CHECKOUT_MEDIO)),
        ("TXLP_BOM",       str(TXLP_BOM)),
        ("TXLP_MEDIO",     str(TXLP_MEDIO)),
    ]:
        html=re.sub(rf"const {k}\s*=\s*[^;]+;", f"const {k}={v};", html, count=1)

    html=re.sub(r"\d{2}/\d{2}/\d{4} · via planilha", date.today().strftime("%d/%m/%Y")+" · via planilha", html)
    return html

# ══ MAIN ═══════════════════════════════════════════════
def main():
    print("="*60)
    print(f"Dashboard — {NOME_CLIENTE} / {chr(44).join(LANCAMENTO_CODS) or 'Todos'}")
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
    _g0 = LANCAMENTO_CODS[0] if LANCAMENTO_CODS else "all"
    total_leads=m_k[_g0]["leads"]
    print(f"  ✓ {total_leads} leads [{_g0}] | {MOEDA_SIMBOLO} {m_k[_g0]['spend']:,.2f} invest.")

    print("\n[PESQUISA]")
    if USAR_PESQUISA:
        df_pes=load_pesquisa()
        pes=pesquisa_process(df_pes, total_leads)
        print(f"  ✓ {pes['total']} respostas")
    else:
        pes=None
        print("  (desativada)")

    print("\n[COMPARAÇÃO LP]")
    _lpv_lancamento = globals().get("LPV_LANCAMENTO")
    if _lpv_lancamento:
        try:
            lpv_data = build_lpv_data(df_meta)
            lpv_list = lpv_data.get("order", [])
            for lv in lpv_list:
                t = lpv_data[lv]["totals"]
                print(f"  {lv}: {t['leads']} leads | CPL {MOEDA_SIMBOLO}{t['cpl']} | invest {MOEDA_SIMBOLO}{t['spend']:.2f}")
        except Exception as e:
            print(f"  ⚠ {e}"); lpv_data = None
    else:
        lpv_data = None
        print("  (desativada)")

    print("\n[VENDAS]")
    vendas_data = None
    if USAR_VENDAS:
        try:
            df_vendas = load_vendas()
            vendas_data = build_vendas_data(df_vendas, df_meta)
            t = vendas_data["totals"]
            print(f"  ✓ {t['vendas']} vendas | receita {MOEDA_SIMBOLO}{t['receita']:,.2f} | "
                  f"invest {MOEDA_SIMBOLO}{t['invest']:,.2f} | ROAS {t['roas']}x")
            for lp in vendas_data["lps"]:
                print(f"     {lp['n']}: {lp['vendas']} vendas | {MOEDA_SIMBOLO}{lp['receita']:,.2f} | ROAS {lp['roas']}x")
        except Exception as e:
            print(f"  ⚠ {e}"); vendas_data = None
    else:
        print("  (desativada)")

    print("\n[HTML]")
    if not Path(TEMPLATE_FILE).exists():
        print(f"  ERRO: {TEMPLATE_FILE} não encontrado"); return
    html=inject_all(TEMPLATE_FILE,m_k,m_d,m_dc,m_raw,m_t,m_bd,pes,lpv_data,vendas_data)
    Path(OUTPUT_FILE).write_text(html,encoding="utf-8")
    print(f"  ✓ {OUTPUT_FILE} ({len(html)//1024}KB)")

    data_json={
        "cliente":NOME_CLIENTE,"cor":COR_ACENTO,"letra":LOGO_LETRA,
        "lancamentos":LANCAMENTO_CODS,"moeda":MOEDA,"moeda_simbolo":MOEDA_SIMBOLO,
        "atualizado":date.today().strftime("%d/%m/%Y"),
        "kpis":{
            "spend":m_k[_g0].get("spend"),
            "leads":m_k[_g0].get("leads"),
            "cpl":m_k[_g0].get("cpl")
        }
    }
    Path("data.json").write_text(json.dumps(data_json,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"  ✓ data.json\n{'='*60}")

if __name__=="__main__":
    main()
