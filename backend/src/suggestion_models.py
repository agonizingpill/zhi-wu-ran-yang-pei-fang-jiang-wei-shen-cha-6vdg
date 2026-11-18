from datetime import datetime
from sqlalchemy import String,Float,Integer,ForeignKey,JSON,CheckConstraint,UniqueConstraint,DateTime,func
from sqlalchemy.orm import Mapped,mapped_column
from .database import Base

class ShadeSuggestion(Base):
    __tablename__='shade_suggestions'
    __table_args__=(
        CheckConstraint('target_l>=0 AND target_l<=100'),
        CheckConstraint('target_a>=-128 AND target_a<=128 AND target_b>=-128 AND target_b<=128'),
        CheckConstraint('cap_a>0 AND cap_b>0 AND cap_c>0 AND cap_a<=100 AND cap_b<=100 AND cap_c<=100'),
        CheckConstraint("state IN ('queued','running','done','failed')"),
    )
    id:Mapped[int]=mapped_column(primary_key=True)
    complaint_id:Mapped[int|None]=mapped_column(ForeignKey('shade_complaints.id'),nullable=True)
    target_l:Mapped[float]=mapped_column(Float)
    target_a:Mapped[float]=mapped_column(Float)
    target_b:Mapped[float]=mapped_column(Float)
    cap_a:Mapped[float]=mapped_column(Float)
    cap_b:Mapped[float]=mapped_column(Float)
    cap_c:Mapped[float]=mapped_column(Float)
    note:Mapped[str]=mapped_column(String(300),default='')
    requested_by:Mapped[str]=mapped_column(String(120))
    training_snapshot:Mapped[dict]=mapped_column(JSON)
    training_count:Mapped[int]=mapped_column(Integer,default=0)
    group_count:Mapped[int]=mapped_column(Integer,default=0)
    state:Mapped[str]=mapped_column(String(20),default='queued')
    attempts:Mapped[int]=mapped_column(Integer,default=0)
    result:Mapped[dict|None]=mapped_column(JSON,nullable=True)
    verdict:Mapped[str]=mapped_column(String(20),default='')
    error:Mapped[str]=mapped_column(String(500),default='')
    created_at:Mapped[datetime]=mapped_column(DateTime,server_default=func.now())
    claimed_at:Mapped[datetime|None]=mapped_column(DateTime,nullable=True)
    completed_at:Mapped[datetime|None]=mapped_column(DateTime,nullable=True)

class ShadeSuggestionAdoption(Base):
    __tablename__='shade_suggestion_adoptions'
    __table_args__=(
        UniqueConstraint('suggestion_id'),
        UniqueConstraint('child_recipe_id'),
        UniqueConstraint('revision_id'),
    )
    id:Mapped[int]=mapped_column(primary_key=True)
    suggestion_id:Mapped[int]=mapped_column(ForeignKey('shade_suggestions.id'))
    parent_recipe_id:Mapped[int]=mapped_column(ForeignKey('dye_recipes.id'))
    child_recipe_id:Mapped[int]=mapped_column(ForeignKey('dye_recipes.id'))
    revision_id:Mapped[int]=mapped_column(ForeignKey('recipe_revisions.id'))
    adopted_by:Mapped[str]=mapped_column(String(120))
    created_at:Mapped[datetime]=mapped_column(DateTime,server_default=func.now())
