from datetime import date
from src.fulfillment_models import DyeLot,DyeIssue,ColorDispatch,ShadeComplaint
import math,random
from sqlalchemy import select,func
from src.database import Base,engine,Session
from src.models import User,DyeRecipe,Swatch,Trial
from src.production_models import RecipeRevision,DyeBatch
from src.auth import hash_password

def seed():
    Base.metadata.create_all(engine)
    with Session() as db:
        for role in ['admin','colorist','viewer']:
            email=f'{role}@qise.test'
            if not db.scalar(select(User).where(User.email==email)):db.add(User(email=email,password=hash_password('Dye2026!'),role=role))
        recipes=[('DY-021','靛蓝亚麻',1.8,.4,.2),('DY-022','苔绿棉麻',.3,1.7,.7),('DY-023','赤陶平纹',.8,.3,1.5)]
        # Sparse calibration recipes span low/high concentrations so the
        # measured-swatch model can learn each dye's effect and be validated by
        # leaving whole recipes out. Lab values are deterministic, not random.
        calibration=[('DY-CAL-01','标定配方 · 中浓度',1.2,.8,.4,[(53.51,.42,-17.87),(53.65,.39,-17.67),(53.96,.66,-18.01)]),
                     ('DY-CAL-02','标定配方 · 高靛蓝',2.2,.9,.6,[(30.82,-.05,-31.28),(30.63,-.18,-30.49),(30.92,-.41,-30.87)]),
                     ('DY-CAL-03','标定配方 · 低浓度',.6,.5,1.1,[(68.83,7.07,.99),(67.93,6.86,1.3),(68.15,6.82,1.29)]),
                     ('DY-CAL-04','标定配方 · 高苔绿',1.5,1.4,.5,[(37.57,.29,-26.64),(37.7,.49,-26.33),(37.81,.3,-26.87)]),
                     ('DY-CAL-05','标定配方 · 高赤陶',.4,.7,1.9,[(66.82,13.83,11.97),(66.91,13.87,11.53),(66.6,13.8,11.26)]),
                     ('DY-CAL-06','标定配方 · 中高浓度',2.,1.1,.25,[(33.05,-2.61,-33.54),(32.67,-2.61,-33.92),(33.04,-2.3,-33.76)]),
                     ('DY-CAL-07','标定配方 · 上限浓度',2.5,1.6,1.,[(12.13,2.4,-37.25),(12.39,1.93,-36.72),(12.27,2.49,-36.96)])]
        for code,name,a,b,c in recipes+[(x[0],x[1],x[2],x[3],x[4]) for x in calibration]:
            if not db.scalar(select(DyeRecipe).where(DyeRecipe.code==code)):db.add(DyeRecipe(code=code,name=name,dye_a=a,dye_b=b,dye_c=c))
        db.flush();rr=db.scalars(select(DyeRecipe).order_by(DyeRecipe.id)).all();rng=random.Random(42)
        for i in range(60):
            lot=['REF-021','SAMPLE-021','SAMPLE-OFF'][i] if i<3 else f'SW-{i:03}'
            if db.scalar(select(Swatch).where(Swatch.lot==lot)):continue
            group=0 if i<3 else i%3
            l,a,b=(48,-2,-25) if i==0 else (48.7,-1.5,-24.5) if i==1 else (62,8,-14) if i==2 else (48+group*9+rng.uniform(-2,2),-2+group*6+rng.uniform(-1,1),-25+group*15+rng.uniform(-1,1))
            spectrum=[round(min(.95,max(.03,.26+group*.11+.1*math.sin(j/5+group)+rng.gauss(0,.012))),5) for j in range(36)]
            db.add(Swatch(recipe_id=rr[group].id,lot=lot,spectrum=spectrum,l=l,a=a,b=b,measured=True))
        prod=db.scalar(select(DyeRecipe).where(DyeRecipe.code=='DY-PROD'))
        if not prod:
            prod=DyeRecipe(code='DY-PROD',name='量产靛蓝基准',dye_a=1.8,dye_b=.4,dye_c=.2,locked=True);db.add(prod);db.flush()
        for lot,l,a,b in [('PROD-REF',48,-2,-25),('PROD-OK',48.5,-1.8,-24.8)]:
            if not db.scalar(select(Swatch).where(Swatch.lot==lot)):db.add(Swatch(recipe_id=prod.id,lot=lot,spectrum=[.3]*36,l=l,a=a,b=b))
        for ci,(code,name,a,b,c,labs) in enumerate(calibration):
            recipe=db.scalar(select(DyeRecipe).where(DyeRecipe.code==code))
            for k,(l,aa,bb) in enumerate(labs):
                lot=f'{code}-{k+1}'
                if db.scalar(select(Swatch).where(Swatch.lot==lot)):continue
                spectrum=[round(min(.95,max(.03,.2+ci*.06+.08*math.sin(j/4+ci)+.01*(k-1))),5) for j in range(36)]
                db.add(Swatch(recipe_id=recipe.id,lot=lot,spectrum=spectrum,l=l,a=aa,b=bb,measured=True))
        db.flush();ref=db.scalar(select(Swatch).where(Swatch.lot=='PROD-REF'));candidate=db.scalar(select(Swatch).where(Swatch.lot=='PROD-OK'))
        trial=db.scalar(select(Trial).where(Trial.recipe_id==prod.id,Trial.state=='approved'))
        if not trial:
            trial=Trial(recipe_id=prod.id,reference_swatch_id=ref.id,candidate_swatch_id=candidate.id,delta_e=.574456,state='approved',note='量产演示基准');db.add(trial);db.flush()
        if not db.scalar(select(DyeBatch).where(DyeBatch.code=='DB-DEMO-001')):db.add(DyeBatch(code='DB-DEMO-001',approved_trial_id=trial.id,kg=250,target_snapshot={'lot':ref.lot,'recipe_id':prod.id,'l':ref.l,'a':ref.a,'b':ref.b,'trial_delta_e':trial.delta_e}))
        for code,component,kg,expiry,state in [('DYE-A-1117','A',80,date(2027,12,31),'active'),('DYE-B-1117','B',40,date(2027,12,31),'active'),('DYE-C-1117','C',20,date(2027,12,31),'active'),('DYE-C-HOLD','C',5,date(2027,12,31),'quarantine'),('DYE-B-OLD','B',5,date(2026,1,1),'active')]:
            if not db.scalar(select(DyeLot).where(DyeLot.code==code)):db.add(DyeLot(code=code,component=component,available_kg=kg,expires_on=expiry,state=state))
        db.commit()
        print({name:db.scalar(select(func.count()).select_from(model)) for name,model in [('users',User),('recipes',DyeRecipe),('swatches',Swatch)]})
if __name__=='__main__':seed()
