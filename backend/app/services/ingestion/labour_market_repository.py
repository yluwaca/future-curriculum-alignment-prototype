from sqlalchemy.orm import Session
from app.models.labour_market_indicator import LabourMarketIndicator
from app.models.labour_market_observation import LabourMarketObservation


def get_or_create_indicator(db: Session, name: str):

    indicator = db.query(LabourMarketIndicator).filter_by(name=name).first()

    if indicator:
        return indicator

    indicator = LabourMarketIndicator(name=name)
    db.add(indicator)
    db.flush()
    db.refresh(indicator)

    return indicator


def insert_observation(
    db: Session,
    indicator_name: str,
    year: int,
    quarter: str,
    value: float,
    source_file: str
):

    indicator = get_or_create_indicator(db, indicator_name)

    obs = LabourMarketObservation(
        indicator_id=indicator.id_indicator,
        year=year,
        quarter=quarter,
        value=value,
        source_file=source_file
    )

    db.add(obs)
