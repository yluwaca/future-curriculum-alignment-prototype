#!/usr/bin/env python
"""Deterministic, leakage-safe examiner evaluation with retained evidence."""
from __future__ import annotations
import argparse, hashlib, json, os, platform, random, sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
import sklearn, xgboost
from sklearn.compose import ColumnTransformer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.linear_model import Ridge
from sklearn.metrics import (accuracy_score, average_precision_score, balanced_accuracy_score,
 brier_score_loss, confusion_matrix, f1_score, log_loss, mean_absolute_error,
 mean_squared_error, precision_recall_curve, precision_recall_fscore_support,
 precision_score, recall_score, roc_auc_score)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

SEED=42
RIGHTS={"examiner_only","public","redistributable"}
TARGET="aligned := 1 when final_alignment_label >= 4; else 0"
LABEL_BASES={"independently_reviewed","researcher_proxy"}
MIN_ALIGNMENT_ROWS=120
MIN_ALIGNMENT_GROUPS=30
MIN_ALIGNMENT_CLASS_ROWS=40

def sha(path):
 h=hashlib.sha256()
 with Path(path).open("rb") as f:
  for b in iter(lambda:f.read(1048576),b""): h.update(b)
 return h.hexdigest()
def dump(path,obj): Path(path).write_text(json.dumps(obj,indent=2,default=str),encoding="utf-8")
def truth(s): return s.astype(str).str.strip().str.lower().isin({"1","true","yes"})
def versions(): return {"python":platform.python_version(),"platform":platform.platform(),"numpy":np.__version__,"pandas":pd.__version__,"scikit_learn":sklearn.__version__,"xgboost":xgboost.__version__}

def alignment_eligibility(df,label_basis="independently_reviewed"):
 if label_basis not in LABEL_BASES: raise ValueError(f"label_basis must be one of {sorted(LABEL_BASES)}")
 req={"observation_id","group_id","observation_date","evidence_cutoff_date","final_alignment_label","label_basis","coding_protocol_version","coder_id_hash","source_document_hash","reviewer_count","independent_reviewers","adjudication_complete","is_synthetic","curriculum_text","labour_market_text","source_id","provenance","rights_status","eligible"}
 if req-set(df): raise ValueError(f"missing alignment columns: {sorted(req-set(df))}")
 o=df.copy(); o["exclusion_reason"]=""; dates=pd.to_datetime(o.observation_date,errors="coerce",utc=True); cuts=pd.to_datetime(o.evidence_cutoff_date,errors="coerce",utc=True)
 independent=label_basis=="independently_reviewed"
 checks=[("declared_ineligible",~truth(o.eligible)),("wrong_label_basis",o.label_basis.astype(str).ne(label_basis)),("synthetic",truth(o.is_synthetic)),("invalid_observation_date",dates.isna()),("invalid_evidence_cutoff",cuts.isna()),("future_evidence",cuts>dates),("missing_coding_protocol",o.coding_protocol_version.fillna("").str.strip().eq("")),("missing_coder_hash",o.coder_id_hash.fillna("").str.strip().eq("")),("missing_source_hash",o.source_document_hash.fillna("").str.strip().eq("")),("insufficient_reviewers",(pd.to_numeric(o.reviewer_count,errors="coerce").fillna(0)<(2 if independent else 1))),("reviewers_not_independent",(~truth(o.independent_reviewers)) if independent else pd.Series(False,index=o.index)),("adjudication_incomplete",(~truth(o.adjudication_complete)) if independent else pd.Series(False,index=o.index)),("empty_curriculum",o.curriculum_text.fillna("").str.strip().eq("")),("empty_labour_market",o.labour_market_text.fillna("").str.strip().eq("")),("rights_not_authorized",~o.rights_status.astype(str).isin(RIGHTS)),("invalid_label",~pd.to_numeric(o.final_alignment_label,errors="coerce").isin([1,2,3,4,5])),("duplicate_observation_id",o.observation_id.duplicated(False))]
 for reason,mask in checks: o.loc[mask&o.exclusion_reason.eq(""),"exclusion_reason"]=reason
 o["included"]=o.exclusion_reason.eq(""); o["date_parsed"]=dates; return o

def pipeline():
 features=ColumnTransformer([("curriculum",TfidfVectorizer(max_features=1000,ngram_range=(1,2)),"curriculum_text"),("labour",TfidfVectorizer(max_features=1000,ngram_range=(1,2)),"labour_market_text")])
 return Pipeline([("features",features),("model",LogisticRegression(max_iter=2000,class_weight="balanced",random_state=SEED))])

def ci(y,p,fn,n=1000):
 rng=np.random.default_rng(SEED); vals=[]; y=np.asarray(y); p=np.asarray(p)
 for _ in range(n):
  idx=rng.integers(0,len(y),len(y))
  try: vals.append(float(fn(y[idx],p[idx])))
  except ValueError: pass
 return {"method":"percentile_bootstrap","replicates":n,"lower_95":float(np.quantile(vals,.025)) if vals else None,"upper_95":float(np.quantile(vals,.975)) if vals else None}

def class_metrics(y,p,t):
 y=np.asarray(y); p=np.asarray(p); pred=(p>=t).astype(int); cm=confusion_matrix(y,pred,labels=[0,1]); pr,rc,f,s=precision_recall_fscore_support(y,pred,labels=[0,1],zero_division=0)
 return {"records":len(y),"threshold":t,"confusion_matrix":{"labels":[0,1],"matrix":cm.tolist(),"tn":int(cm[0,0]),"fp":int(cm[0,1]),"fn":int(cm[1,0]),"tp":int(cm[1,1])},"accuracy":accuracy_score(y,pred),"balanced_accuracy":balanced_accuracy_score(y,pred),"precision":precision_score(y,pred,zero_division=0),"recall":recall_score(y,pred,zero_division=0),"f1":f1_score(y,pred,zero_division=0),"macro_f1":f1_score(y,pred,average="macro",zero_division=0),"per_class":{"0":{"precision":pr[0],"recall":rc[0],"f1":f[0],"support":int(s[0])},"1":{"precision":pr[1],"recall":rc[1],"f1":f[1],"support":int(s[1])}},"brier":brier_score_loss(y,p),"log_loss":log_loss(y,np.c_[1-p,p],labels=[0,1]),"roc_auc":roc_auc_score(y,p) if len(set(y))==2 else None,"pr_auc":average_precision_score(y,p) if len(set(y))==2 else None,"uncertainty":{"f1":ci(y,p,lambda a,b:f1_score(a,b>=t,zero_division=0)),"accuracy":ci(y,p,lambda a,b:accuracy_score(a,b>=t))}}

def run_alignment(inp,out,label_basis="independently_reviewed"):
 raw=pd.read_csv(inp); ledger=alignment_eligibility(raw,label_basis); data=ledger[ledger.included].copy()
 if len(data)<MIN_ALIGNMENT_ROWS: raise ValueError(f"not evaluable: {len(data)} eligible rows; require {MIN_ALIGNMENT_ROWS}")
 data["target"]=(pd.to_numeric(data.final_alignment_label)>=4).astype(int)
 if data.group_id.nunique()<MIN_ALIGNMENT_GROUPS or data.target.value_counts().min()<MIN_ALIGNMENT_CLASS_ROWS: raise ValueError(f"not evaluable: require {MIN_ALIGNMENT_GROUPS} groups and {MIN_ALIGNMENT_CLASS_ROWS} rows per class")
 groups=data.groupby("group_id").date_parsed.min().sort_values().index.tolist(); cut=int(len(groups)*.8); dev=data[data.group_id.isin(groups[:cut])].sort_values("date_parsed"); test=data[data.group_id.isin(groups[cut:])].sort_values("date_parsed")
 if dev.target.nunique()<2 or test.target.nunique()<2: raise ValueError("not evaluable: both splits require both classes")
 gids=list(dict.fromkeys(dev.group_id)); foldpred=[]; folds=[]
 for fold in range(3):
  end=max(2,int(len(gids)*(.5+.15*fold))); vg=gids[end:min(len(gids),end+max(1,len(gids)//10))]; tr=dev[dev.group_id.isin(gids[:end])]; va=dev[dev.group_id.isin(vg)]
  if va.empty or tr.target.nunique()<2: continue
  m=pipeline().fit(tr,tr.target); p=m.predict_proba(va)[:,1]; folds.append({"fold":fold+1,"train_records":len(tr),"validation_records":len(va),"f1_at_0_5":f1_score(va.target,p>=.5,zero_division=0)})
  foldpred += [{"fold":fold+1,"observation_id":r.observation_id,"actual":int(r.target),"probability":float(q)} for (_,r),q in zip(va.iterrows(),p)]
 fp=pd.DataFrame(foldpred); threshold=.5
 if len(fp) and fp.actual.nunique()==2:
  precision,recall,ts=precision_recall_curve(fp.actual,fp.probability); score=2*precision[:-1]*recall[:-1]/np.maximum(precision[:-1]+recall[:-1],1e-12); threshold=float(ts[int(np.argmax(score))])
 model=pipeline().fit(dev,dev.target); prob=model.predict_proba(test)[:,1]; pred=(prob>=threshold).astype(int)
 stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"); run=out/f"alignment_{label_basis}_{stamp}"; run.mkdir(parents=True)
 ledger.drop(columns="date_parsed").to_csv(run/"eligibility_ledger.csv",index=False); pd.concat([dev.assign(split="development"),test.assign(split="test")])[["observation_id","group_id","observation_date","target","split"]].to_csv(run/"split_membership.csv",index=False)
 pd.DataFrame({"observation_id":test.observation_id,"group_id":test.group_id,"actual":test.target,"probability":prob,"predicted":pred,"correct":pred==test.target}).to_csv(run/"predictions.csv",index=False); fp.to_csv(run/"fold_predictions.csv",index=False)
 metrics=class_metrics(test.target,prob,threshold); majority=int(dev.target.mode().iloc[0]); metrics["baselines"]={"majority":class_metrics(test.target,np.full(len(test),majority,float),.5),"development_prevalence":class_metrics(test.target,np.full(len(test),float(dev.target.mean())),.5)}; metrics["folds"]=folds; metrics["class_balance"]={k:{str(a):int(b) for a,b in d.target.value_counts().sort_index().items()} for k,d in [("development",dev),("test",test)]}; dump(run/"metrics.json",metrics)
 evidence_status="confirmatory_candidate" if label_basis=="independently_reviewed" else "exploratory_proxy_only"
 manifest={"schema_version":"1.1","status":"complete","evidence_status":evidence_status,"task":"alignment_classification","label_basis":label_basis,"run_id":run.name,"created_utc":datetime.now(timezone.utc).isoformat(),"input":{"path":str(inp.resolve()),"sha256":sha(inp),"records":len(raw),"eligible_records":len(data)},"target_definition":TARGET,"split_policy":"chronological groups; final 20% untouched test; expanding-window development CV","seed":SEED,"operating_threshold":threshold,"parameters":model.get_params(),"software":versions(),"outputs":{}}
 for f in run.iterdir(): manifest["outputs"][f.name]=sha(f)
 dump(run/"manifest.json",manifest); print(run)

def forecast_eligibility(df):
 req={"series_id","period","frequency","value","source_id","provenance","rights_status","is_synthetic","eligible"}
 if req-set(df): raise ValueError(f"missing forecast columns: {sorted(req-set(df))}")
 o=df.copy(); o["exclusion_reason"]=""; o["period_parsed"]=pd.to_datetime(o.period,errors="coerce",utc=True); o["value_parsed"]=pd.to_numeric(o.value,errors="coerce")
 checks=[("declared_ineligible",~truth(o.eligible)),("synthetic",truth(o.is_synthetic)),("invalid_period",o.period_parsed.isna()),("invalid_frequency",~o.frequency.astype(str).str.lower().isin({"monthly","quarterly"})),("invalid_value",o.value_parsed.isna()|o.value_parsed.lt(0)),("rights_not_authorized",~o.rights_status.astype(str).isin(RIGHTS)),("duplicate_series_period",o.duplicated(["series_id","period"],False))]
 for reason,mask in checks:o.loc[mask&o.exclusion_reason.eq(""),"exclusion_reason"]=reason
 o["included"]=o.exclusion_reason.eq(""); return o

def _regular_periods(g):
 freq=str(g.frequency.iloc[0]).lower()
 if g.frequency.astype(str).str.lower().nunique()!=1:return False
 periods=g.period_parsed.dt.tz_convert(None).dt.to_period("M" if freq=="monthly" else "Q")
 return bool(len(periods)==len(pd.period_range(periods.iloc[0],periods.iloc[-1],freq="M" if freq=="monthly" else "Q")))

def _regression_metrics(g):
 actual=np.asarray(g.actual,float); prediction=np.asarray(g.prediction,float)
 result={"records":int(len(g)),"mae":float(mean_absolute_error(actual,prediction)),"rmse":float(mean_squared_error(actual,prediction)**.5),"smape_pct":float(np.mean(200*np.abs(actual-prediction)/np.maximum(np.abs(actual)+np.abs(prediction),1e-12)))}
 rng=np.random.default_rng(SEED); boot=[]
 for _ in range(1000):
  idx=rng.integers(0,len(actual),len(actual)); boot.append(float(mean_absolute_error(actual[idx],prediction[idx])))
 result["uncertainty"]={"metric":"mae","method":"record_percentile_bootstrap","replicates":1000,"lower_95":float(np.quantile(boot,.025)),"upper_95":float(np.quantile(boot,.975))}
 return result

def _lag_rows(values,lags,end):
 """Supervised rows whose targets are strictly before ``end``."""
 X=[]; y=[]
 for target in range(lags,end):
  X.append(values[target-lags:target]); y.append(values[target])
 return np.asarray(X,float),np.asarray(y,float)

def run_forecast(inp,out,horizon):
 if horizon<1: raise ValueError("horizon must be at least 1")
 raw=pd.read_csv(inp); ledger=forecast_eligibility(raw); clean=ledger[ledger.included].sort_values(["series_id","period_parsed"]); accepted=[]; rejected={}
 for sid,g in clean.groupby("series_id",sort=True):
  frequency=g.frequency.astype(str).str.lower().iloc[0] if len(g) else ""
  seasonal_lag=12 if frequency=="monthly" else 4
  minimum=max(2*seasonal_lag+2*horizon,4*horizon)
  reason=("mixed_or_irregular_periods" if not _regular_periods(g) else ("insufficient_history" if len(g)<minimum else ("constant_or_zero_series" if g.value_parsed.nunique()<2 or g.value_parsed.sum()==0 else None)))
  if reason: rejected[str(sid)]=reason
  else: accepted.append(g)
 if not accepted: raise ValueError(f"not evaluable: no eligible forecast series; rejected={rejected}")
 data=pd.concat(accepted); rows=[]; memberships=[]
 for sid,g in data.groupby("series_id",sort=True):
  vals=g.value_parsed.to_numpy(float); periods=g.period_parsed.tolist(); frequency=str(g.frequency.iloc[0]).lower(); seasonal_lag=12 if frequency=="monthly" else 4; lags=seasonal_lag
  test_start=len(g)-horizon; dev_start=max(lags+4,test_start-3*horizon)
  for i in range(dev_start,len(g)):
   split="test" if i>=test_start else "development"; hist=vals[:i]; actual=vals[i]
   X_train,y_train=_lag_rows(vals,lags,i)
   # Scaling and fitting see only lag windows whose targets precede this origin.
   candidate=Pipeline([("scale",StandardScaler()),("ridge",Ridge(alpha=1.0))]).fit(X_train,y_train)
   candidates={
    "ridge_autoregression":float(candidate.predict(hist[-lags:].reshape(1,-1))[0]),
    "last_value":float(hist[-1]),
    "seasonal_naive":float(hist[-seasonal_lag]),
    "drift":float(hist[-1]+(hist[-1]-hist[0])/max(1,len(hist)-1)),
   }
   membership_id=f"{sid}|{g.period.iloc[i]}"
   memberships.append({"evaluation_record_id":membership_id,"series_id":sid,"origin_period":str(g.period.iloc[i-1]),"target_period":str(g.period.iloc[i]),"split":split,"training_target_end":str(g.period.iloc[i-1]),"training_rows":len(y_train)})
   for name,pred in candidates.items(): rows.append({"evaluation_record_id":membership_id,"series_id":sid,"origin_period":str(g.period.iloc[i-1]),"target_period":str(g.period.iloc[i]),"forecast_step":1,"split":split,"model":name,"actual":actual,"prediction":pred,"residual":float(actual-pred),"training_rows":len(y_train)})
 preds=pd.DataFrame(rows); test_preds=preds[preds.split.eq("test")].copy(); dev_preds=preds[preds.split.eq("development")].copy()
 expected=set(test_preds[test_preds.model.eq("ridge_autoregression")].evaluation_record_id)
 if any(set(g.evaluation_record_id)!=expected for _,g in test_preds.groupby("model")): raise RuntimeError("baseline record mismatch")
 metrics={name:_regression_metrics(g) for name,g in test_preds.groupby("model")}
 for name,g in dev_preds.groupby("model"):
  metrics[name]["development_rolling_origin"]=_regression_metrics(g)
  metrics[name]["folds"]=[dict(fold=int(n+1),target_period=str(period),**_regression_metrics(fg)) for n,(period,fg) in enumerate(g.groupby("target_period",sort=True))]
 stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"); run=out/f"forecast_{stamp}"; run.mkdir(parents=True); ledger.drop(columns=["period_parsed","value_parsed"]).to_csv(run/"eligibility_ledger.csv",index=False); pd.DataFrame(memberships).to_csv(run/"split_membership.csv",index=False); preds.to_csv(run/"predictions.csv",index=False); dump(run/"metrics.json",metrics)
 manifest={"schema_version":"1.1","status":"complete","task":"chronological_panel_forecast","run_id":run.name,"created_utc":datetime.now(timezone.utc).isoformat(),"input":{"path":str(inp.resolve()),"sha256":sha(inp),"records":len(raw),"eligible_records":len(data)},"target_definition":"next observed non-negative demand count for the same series and regular period cadence","split_policy":f"per-series rolling one-step origins; final {horizon} targets are locked test; preceding up to {3*horizon} targets are development folds; every feature and fitted target strictly precedes its forecast target","model":{"name":"ridge_autoregression","lags":"one seasonal cycle (12 monthly or 4 quarterly)","alpha":1.0,"scaling":"StandardScaler fitted separately at each origin on prior training windows only"},"baselines":["last_value","seasonal_naive","drift"],"baseline_record_policy":"all models evaluated on exactly the same series-target records","horizon":horizon,"seed":SEED,"rejected_series":rejected,"software":versions(),"outputs":{}}
 for f in run.iterdir():manifest["outputs"][f.name]=sha(f)
 dump(run/"manifest.json",manifest); print(run)

def main():
 p=argparse.ArgumentParser(); sub=p.add_subparsers(dest="task",required=True)
 for name in ("alignment","forecast"):
  q=sub.add_parser(name);q.add_argument("--input",type=Path,required=True);q.add_argument("--output",type=Path,required=True);q.add_argument("--horizon",type=int,default=3);q.add_argument("--label-basis",choices=sorted(LABEL_BASES),default="independently_reviewed")
 a=p.parse_args(); random.seed(SEED);np.random.seed(SEED);os.environ.setdefault("PYTHONHASHSEED",str(SEED));a.output.mkdir(parents=True,exist_ok=True)
 run_alignment(a.input,a.output,a.label_basis) if a.task=="alignment" else run_forecast(a.input,a.output,a.horizon)
if __name__=="__main__": main()
