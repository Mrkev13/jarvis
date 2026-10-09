"""Durable Fitness & Rehab definitions, sessions and measurements (MRK-33)."""
from alembic import op
import sqlalchemy as sa

revision = '0021_fitness'
down_revision = '0020_calendar_source_presence'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('fitness_exercises',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('category', sa.String(80), nullable=False),
        sa.Column('equipment', sa.String(120), nullable=True),
        sa.Column('muscle_group', sa.String(120), nullable=True),
        sa.Column('type', sa.String(20), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('archived_at', sa.DateTime(), nullable=True),
        sa.CheckConstraint("type IN ('strength', 'bodyweight', 'duration', 'distance')", name='ck_fitness_exercises_type'),
        sa.PrimaryKeyConstraint('id'))
    op.create_table('fitness_rehab_exercises',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('type', sa.String(20), nullable=False),
        sa.Column('body_area', sa.String(120), nullable=True),
        sa.Column('instructions', sa.Text(), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('archived_at', sa.DateTime(), nullable=True),
        sa.CheckConstraint("type IN ('strength', 'bodyweight', 'duration', 'distance')", name='ck_fitness_rehab_exercises_type'),
        sa.PrimaryKeyConstraint('id'))
    op.create_table('fitness_rehab_sessions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('performed_on', sa.Date(), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'))
    op.create_index('ix_fitness_rehab_sessions_performed_on', 'fitness_rehab_sessions', ['performed_on'], unique=False)
    op.create_table('fitness_workouts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('performed_on', sa.Date(), nullable=False),
        sa.Column('title', sa.String(200), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('duration_minutes', sa.Integer(), nullable=True),
        sa.Column('source', sa.String(20), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint('duration_minutes IS NULL OR (duration_minutes > 0 AND duration_minutes <= 10080)', name='ck_fitness_workouts_duration'),
        sa.PrimaryKeyConstraint('id'))
    op.create_index('ix_fitness_workouts_performed_on', 'fitness_workouts', ['performed_on'], unique=False)
    op.create_table('fitness_rehab_entries',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('rehab_session_id', sa.Integer(), nullable=False),
        sa.Column('rehab_exercise_id', sa.Integer(), nullable=False),
        sa.Column('exercise_name', sa.String(120), nullable=False),
        sa.Column('exercise_type', sa.String(20), nullable=False),
        sa.Column('order_index', sa.Integer(), nullable=False),
        sa.Column('sets', sa.Integer(), nullable=False),
        sa.Column('reps', sa.Integer(), nullable=True),
        sa.Column('weight_kg', sa.Float(), nullable=True),
        sa.Column('duration_seconds', sa.Integer(), nullable=True),
        sa.Column('distance_m', sa.Float(), nullable=True),
        sa.Column('pain_before', sa.Float(), nullable=True),
        sa.Column('pain_after', sa.Float(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.CheckConstraint('distance_m IS NULL OR (distance_m > 0 AND distance_m <= 10000000)', name='ck_fitness_rehab_entry_distance_m'),
        sa.CheckConstraint('duration_seconds IS NULL OR (duration_seconds > 0 AND duration_seconds <= 604800)', name='ck_fitness_rehab_entry_duration_seconds'),
        sa.CheckConstraint('order_index >= 0 AND order_index <= 199', name='ck_fitness_rehab_entry_order'),
        sa.CheckConstraint('pain_after IS NULL OR (pain_after >= 0 AND pain_after <= 10)', name='ck_fitness_rehab_entry_pain_after'),
        sa.CheckConstraint('pain_before IS NULL OR (pain_before >= 0 AND pain_before <= 10)', name='ck_fitness_rehab_entry_pain_before'),
        sa.CheckConstraint('reps IS NULL OR (reps >= 0 AND reps <= 10000)', name='ck_fitness_rehab_entry_reps'),
        sa.CheckConstraint('sets >= 1 AND sets <= 100', name='ck_fitness_rehab_entry_sets'),
        sa.CheckConstraint("exercise_type IN ('strength', 'bodyweight', 'duration', 'distance')", name='ck_fitness_rehab_entry_type'),
        sa.CheckConstraint('weight_kg IS NULL OR (weight_kg >= 0 AND weight_kg <= 10000)', name='ck_fitness_rehab_entry_weight_kg'),
        sa.ForeignKeyConstraint(['rehab_session_id'], ['fitness_rehab_sessions.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['rehab_exercise_id'], ['fitness_rehab_exercises.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('rehab_session_id', 'order_index', name='uq_fitness_rehab_entry_order'))
    op.create_index('ix_fitness_rehab_entries_rehab_exercise_id', 'fitness_rehab_entries', ['rehab_exercise_id'], unique=False)
    op.create_index('ix_fitness_rehab_entries_rehab_session_id', 'fitness_rehab_entries', ['rehab_session_id'], unique=False)
    op.create_table('fitness_workout_sets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('workout_session_id', sa.Integer(), nullable=False),
        sa.Column('exercise_id', sa.Integer(), nullable=False),
        sa.Column('exercise_name', sa.String(120), nullable=False),
        sa.Column('exercise_type', sa.String(20), nullable=False),
        sa.Column('order_index', sa.Integer(), nullable=False),
        sa.Column('reps', sa.Integer(), nullable=True),
        sa.Column('weight_kg', sa.Float(), nullable=True),
        sa.Column('duration_seconds', sa.Integer(), nullable=True),
        sa.Column('distance_m', sa.Float(), nullable=True),
        sa.Column('rir', sa.Float(), nullable=True),
        sa.Column('completed', sa.Boolean(), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.CheckConstraint('distance_m IS NULL OR (distance_m > 0 AND distance_m <= 10000000)', name='ck_fitness_workout_set_distance_m'),
        sa.CheckConstraint('duration_seconds IS NULL OR (duration_seconds > 0 AND duration_seconds <= 604800)', name='ck_fitness_workout_set_duration_seconds'),
        sa.CheckConstraint('order_index >= 0 AND order_index <= 199', name='ck_fitness_workout_set_order'),
        sa.CheckConstraint('reps IS NULL OR (reps >= 0 AND reps <= 10000)', name='ck_fitness_workout_set_reps'),
        sa.CheckConstraint('rir IS NULL OR (rir >= 0 AND rir <= 10)', name='ck_fitness_workout_set_rir'),
        sa.CheckConstraint("exercise_type IN ('strength', 'bodyweight', 'duration', 'distance')", name='ck_fitness_workout_set_type'),
        sa.CheckConstraint('weight_kg IS NULL OR (weight_kg >= 0 AND weight_kg <= 10000)', name='ck_fitness_workout_set_weight_kg'),
        sa.ForeignKeyConstraint(['workout_session_id'], ['fitness_workouts.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['exercise_id'], ['fitness_exercises.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('workout_session_id', 'order_index', name='uq_fitness_workout_set_order'))
    op.create_index('ix_fitness_workout_sets_exercise_id', 'fitness_workout_sets', ['exercise_id'], unique=False)
    op.create_index('ix_fitness_workout_sets_workout_session_id', 'fitness_workout_sets', ['workout_session_id'], unique=False)


def downgrade():
    op.drop_index('ix_fitness_workout_sets_exercise_id', table_name='fitness_workout_sets')
    op.drop_index('ix_fitness_workout_sets_workout_session_id', table_name='fitness_workout_sets')
    op.drop_table('fitness_workout_sets')
    op.drop_index('ix_fitness_rehab_entries_rehab_exercise_id', table_name='fitness_rehab_entries')
    op.drop_index('ix_fitness_rehab_entries_rehab_session_id', table_name='fitness_rehab_entries')
    op.drop_table('fitness_rehab_entries')
    op.drop_index('ix_fitness_workouts_performed_on', table_name='fitness_workouts')
    op.drop_table('fitness_workouts')
    op.drop_index('ix_fitness_rehab_sessions_performed_on', table_name='fitness_rehab_sessions')
    op.drop_table('fitness_rehab_sessions')
    op.drop_table('fitness_rehab_exercises')
    op.drop_table('fitness_exercises')
