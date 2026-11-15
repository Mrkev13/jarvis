# MRK-114: compatibility smoke, piped into `python -` INSIDE an application container (old or new image) by
# deploy-migration-v3.sh. Uses only long-standing modules (main, database), so it runs on older releases too.
# Imports the whole application (all models registered) and SELECTs every mapped entity, i.e. every column the code
# expects must exist in the database it is connected to. Read-only: the session is rolled back.
import importlib
import sys

sys.path.insert(0, ".")
importlib.import_module("main")  # registers every model
from database import Base, SessionLocal  # noqa: E402
from sqlalchemy import select  # noqa: E402

count = 0
with SessionLocal() as db:
    for mapper in sorted(Base.registry.mappers, key=lambda m: m.class_.__name__):
        db.execute(select(mapper.class_).limit(5)).all()
        count += 1
    db.rollback()
print(f"ORM_SMOKE_OK mapped={count}")
