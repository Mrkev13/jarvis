"""Fitness contributions: completed facts without scheduled Calendar occupancy."""
from context_format import short
from module_contracts import ChangeSource,ContextSection,EntityRef,ModuleIntegrations,SearchSource,TodaySource,event_changes
from modules.fitness import service
from modules.fitness.models import Exercise,WorkoutSession,RehabExercise,RehabSession
from modules.fitness.router import router
from today_types import TodayItem

HREFS={'fitness_exercise':'/fitness?exercise={id}','fitness_workout':'/fitness?workout={id}',
       'fitness_rehab_exercise':'/fitness?rehab_exercise={id}','fitness_rehab_session':'/fitness?rehab_session={id}'}
EVENTS={f'fitness.{kind}.{action}' for kind in ('exercise','rehab_exercise') for action in ('created','updated','archived','restored')}
EVENTS.update(f'fitness.{kind}.{action}' for kind in ('workout','rehab_session') for action in ('created','updated'))


def search_fitness(db,q):
    for row in db.query(Exercise).order_by(Exercise.name,Exercise.id).limit(500).all():
        yield 'fitness_exercise',row.id,row.name,'Cvik'+(' · archivovaný' if not row.active else ''),'fitness cvik','fitness',HREFS['fitness_exercise'].format(id=row.id)
    for row in db.query(WorkoutSession).order_by(WorkoutSession.performed_on.desc(),WorkoutSession.id.desc()).limit(500).all():
        yield 'fitness_workout',row.id,row.title or 'Trénink',row.performed_on.isoformat(),'fitness trenink','fitness',HREFS['fitness_workout'].format(id=row.id)
    for row in db.query(RehabExercise).order_by(RehabExercise.name,RehabExercise.id).limit(500).all():
        yield 'fitness_rehab_exercise',row.id,row.name,'Rehab cvik'+(' · archivovaný' if not row.active else ''),'fitness rehab rehabilitace','fitness',HREFS['fitness_rehab_exercise'].format(id=row.id)


def today_fitness(c):
    items=[]
    for row in c.db.query(WorkoutSession).filter(WorkoutSession.performed_on==c.today).order_by(WorkoutSession.id).limit(100).all():
        items.append(TodayItem(id=f'fitness_workout:{row.id}',type='fitness_workout',title=row.title or 'Trénink zapsán',
                               subtitle='Historie tréninku',area='fitness',date=c.today.isoformat(),status='done',
                               href=HREFS['fitness_workout'].format(id=row.id),source_id=row.id))
    for row in c.db.query(RehabSession).filter(RehabSession.performed_on==c.today).order_by(RehabSession.id).limit(100).all():
        items.append(TodayItem(id=f'fitness_rehab_session:{row.id}',type='fitness_rehab_session',title='Rehabilitace zapsána',
                               subtitle='Historie rehabilitace',area='fitness',date=c.today.isoformat(),status='done',
                               href=HREFS['fitness_rehab_session'].format(id=row.id),source_id=row.id))
    return items


def context_fitness(req):
    data=service.progress(req.db,today=req.today)
    lines=[f"Fitness tento týden: {data['week_workouts']} tréninků; {data['week_rehab_sessions']} rehab záznamů."]
    if data['recent_workouts']:
        row=data['recent_workouts'][0]
        lines.append(f"Poslední trénink: {row['performed_on']} {short(row['title'] or 'Trénink',50)} ({len(row['sets'])} sérií).")
        # Values from this one eagerly-loaded workout; no per-exercise progress query.
        for entry in [s for s in row['sets'] if s['completed']][:3]:
            values=' '.join(f'{entry[key]} {unit}' for key,unit in [('reps','opak.'),('weight_kg','kg'),('duration_seconds','s'),('distance_m','m')] if entry[key] is not None)
            lines.append(f"Cvik: {short(entry['exercise_name'],30)} {values}.")
    if data['recent_rehab_sessions']:
        row=data['recent_rehab_sessions'][0]
        lines.append(f"Poslední rehabilitace: {row['performed_on']} ({len(row['entries'])} položek).")
    return lines


INTEGRATIONS=ModuleIntegrations(
    search=(SearchSource('fitness',95,search_fitness),),
    today=(TodaySource('fitness',40,timeline=today_fitness),),
    context=(ContextSection('fitness',('fitness','cvic','trenink','workout','rehab','rehabilit'),order=90,build=context_fitness),),
    changes=(ChangeSource('fitness',from_event=event_changes(HREFS,{key:'Fitness záznam změněn' for key in EVENTS})),),
    entity_refs=tuple(EntityRef(kind,href) for kind,href in HREFS.items()),
    routers=(router,),
)
