from pathlib import Path
import shutil
import sys
import uuid
import pandas as pd
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from run_locked_evaluation import alignment_eligibility, forecast_eligibility, run_forecast

@pytest.fixture
def work_path():
 path=Path(__file__).resolve().parents[1]/".test_tmp"/uuid.uuid4().hex
 path.mkdir(parents=True)
 try: yield path
 finally: shutil.rmtree(path,ignore_errors=True)

def row(**changes):
 r={"observation_id":"o1","group_id":"g1","observation_date":"2025-01-31","evidence_cutoff_date":"2025-01-01","final_alignment_label":4,"label_basis":"independently_reviewed","coding_protocol_version":"1.0","coder_id_hash":"coder-hash","source_document_hash":"document-hash","reviewer_count":2,"independent_reviewers":True,"adjudication_complete":True,"is_synthetic":False,"curriculum_text":"python databases","labour_market_text":"python sql","source_id":"s1","provenance":"authorized","rights_status":"examiner_only","eligible":True};r.update(changes);return r
def test_excludes_synthetic_and_future_evidence():
 o=alignment_eligibility(pd.DataFrame([row(is_synthetic=True),row(observation_id="o2",evidence_cutoff_date="2025-02-01")]))
 assert o.exclusion_reason.tolist()==["synthetic","future_evidence"]
def test_requires_independent_completed_review():
 o=alignment_eligibility(pd.DataFrame([row(independent_reviewers=False),row(observation_id="o2",adjudication_complete=False)]))
 assert o.exclusion_reason.tolist()==["reviewers_not_independent","adjudication_incomplete"]
def test_duplicate_observation_ids_excluded():
 assert not alignment_eligibility(pd.DataFrame([row(),row(group_id="g2")])).included.any()
def test_proxy_labels_are_separate_and_require_one_coder():
 proxy=row(label_basis="researcher_proxy",reviewer_count=1,independent_reviewers=False,adjudication_complete=False)
 assert alignment_eligibility(pd.DataFrame([proxy]),"researcher_proxy").included.iloc[0]
 assert not alignment_eligibility(pd.DataFrame([proxy]),"independently_reviewed").included.iloc[0]
def test_forecast_duplicate_period_excluded():
 b={"series_id":"s","period":"2025-01-01","frequency":"monthly","value":1,"source_id":"x","provenance":"public","rights_status":"public","is_synthetic":False,"eligible":True}
 assert set(forecast_eligibility(pd.DataFrame([b,b])).exclusion_reason)=={"duplicate_series_period"}

def forecast_panel(periods=30,constant=False):
 dates=pd.date_range("2022-01-01",periods=periods,freq="MS")
 return pd.DataFrame([{"series_id":"wc_python","period":d.date().isoformat(),"frequency":"monthly","value":5 if constant else 5+i%7+i//6,"source_id":"source-a","provenance":"public export","rights_status":"public","is_synthetic":False,"eligible":True} for i,d in enumerate(dates)])

def test_forecast_refuses_irregular_and_constant_series(work_path):
 irregular=forecast_panel().drop(index=5)
 source=work_path/"irregular.csv"; irregular.to_csv(source,index=False)
 try: run_forecast(source,work_path/"out",3)
 except ValueError as exc: assert "mixed_or_irregular_periods" in str(exc)
 else: raise AssertionError("irregular series should be refused")
 constant=forecast_panel(constant=True); source=work_path/"constant.csv"; constant.to_csv(source,index=False)
 try: run_forecast(source,work_path/"out2",3)
 except ValueError as exc: assert "constant_or_zero_series" in str(exc)
 else: raise AssertionError("constant series should be refused")

def test_forecast_rolling_origins_use_identical_records_and_prior_targets(work_path):
 source=work_path/"panel.csv"; forecast_panel().to_csv(source,index=False); out=work_path/"runs"
 run_forecast(source,out,3); run=next(out.iterdir())
 predictions=pd.read_csv(run/"predictions.csv"); membership=pd.read_csv(run/"split_membership.csv")
 test=predictions[predictions.split.eq("test")]
 record_sets=[set(g.evaluation_record_id) for _,g in test.groupby("model")]
 assert len(record_sets)==4 and all(ids==record_sets[0] for ids in record_sets)
 assert len(record_sets[0])==3
 assert (pd.to_datetime(membership.training_target_end)<pd.to_datetime(membership.target_period)).all()
 assert set(test.forecast_step)=={1}
