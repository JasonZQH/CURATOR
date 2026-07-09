"""Define database migrations for Curator Phase 0 state."""

PHASE0_SCHEMA_SQL = """
create table if not exists sessions (
    id text primary key,
    project_root text not null,
    mode text not null,
    status text not null,
    created_at text not null,
    updated_at text not null,
    metadata_json text not null default '{}'
);

create table if not exists tasks (
    id text primary key,
    session_id text not null,
    role text not null,
    status text not null,
    title text not null,
    description text not null default '',
    created_at text,
    updated_at text,
    metadata_json text not null default '{}',
    foreign key (session_id) references sessions(id)
);

create table if not exists messages (
    id text primary key,
    session_id text not null,
    task_id text,
    role text not null,
    type text not null,
    content text not null,
    created_at text not null,
    metadata_json text not null default '{}',
    foreign key (session_id) references sessions(id),
    foreign key (task_id) references tasks(id)
);

create table if not exists events (
    id text primary key,
    session_id text not null,
    task_id text,
    type text not null,
    created_at text not null,
    payload_json text not null default '{}',
    foreign key (session_id) references sessions(id),
    foreign key (task_id) references tasks(id)
);

create table if not exists loop_runs (
    id text primary key,
    session_id text not null,
    contract_id text not null,
    template_id text not null,
    status text not null,
    created_at text not null,
    updated_at text not null,
    completed_at text,
    metadata_json text not null default '{}'
);

create table if not exists loop_iterations (
    id text primary key,
    loop_run_id text not null,
    session_id text not null,
    task_id text,
    sequence integer not null,
    step_type text not null,
    role text not null,
    status text not null,
    started_at text not null,
    completed_at text,
    metadata_json text not null default '{}',
    foreign key (loop_run_id) references loop_runs(id)
);

create table if not exists loop_decisions (
    id text primary key,
    loop_run_id text not null,
    iteration_id text not null,
    decision text not null,
    stop_condition text,
    reason text not null,
    created_at text not null,
    metadata_json text not null default '{}',
    foreign key (loop_run_id) references loop_runs(id),
    foreign key (iteration_id) references loop_iterations(id)
);

create table if not exists evidence_refs (
    id text primary key,
    session_id text not null,
    loop_run_id text not null,
    iteration_id text not null,
    kind text not null,
    uri text not null,
    summary text not null,
    producer_role text not null,
    created_at text not null,
    content_hash text,
    metadata_json text not null default '{}',
    foreign key (loop_run_id) references loop_runs(id),
    foreign key (iteration_id) references loop_iterations(id)
);

create table if not exists role_selections (
    id text primary key,
    session_id text not null,
    loop_run_id text not null,
    role_id text not null,
    display_name text not null,
    matched_signals_json text not null default '[]',
    score integer not null,
    reason text not null,
    created_at text not null,
    metadata_json text not null default '{}',
    foreign key (loop_run_id) references loop_runs(id)
);

create table if not exists goals (
    id text primary key,
    source_request text not null,
    summary text not null,
    status text not null,
    current_revision_id text,
    created_at text not null,
    updated_at text not null,
    metadata_json text not null default '{}'
);

create table if not exists goal_revisions (
    id text primary key,
    goal_id text not null,
    revision integer not null,
    status text not null,
    contract_json text not null,
    created_at text not null,
    accepted_at text not null,
    metadata_json text not null default '{}',
    foreign key (goal_id) references goals(id),
    unique (goal_id, revision)
);

create table if not exists goal_runs (
    id text primary key,
    goal_id text not null,
    goal_revision_id text not null,
    session_id text not null,
    loop_run_id text not null,
    status text not null,
    started_at text not null,
    completed_at text,
    metadata_json text not null default '{}',
    foreign key (goal_id) references goals(id),
    foreign key (goal_revision_id) references goal_revisions(id),
    foreign key (loop_run_id) references loop_runs(id)
);

create table if not exists discovery_sessions (
    id text primary key,
    project_root text not null,
    status text not null,
    goal_id text,
    created_at text not null,
    updated_at text not null,
    metadata_json text not null default '{}'
);

create table if not exists discussion_turns (
    id text primary key,
    discovery_session_id text not null,
    role text not null,
    content text not null,
    created_at text not null,
    metadata_json text not null default '{}',
    foreign key (discovery_session_id) references discovery_sessions(id)
);

create table if not exists goal_drafts (
    id text primary key,
    discovery_session_id text not null,
    goal_id text not null,
    status text not null,
    contract_json text not null default '{}',
    created_at text not null,
    updated_at text not null,
    metadata_json text not null default '{}',
    foreign key (discovery_session_id) references discovery_sessions(id)
);

create table if not exists pause_records (
    id text primary key,
    loop_run_id text not null,
    session_id text not null,
    iteration_id text not null,
    task_id text,
    reason text not null,
    question text not null,
    requested_input text not null,
    resume_mode text not null,
    status text not null,
    created_at text not null,
    resolved_at text,
    metadata_json text not null default '{}',
    foreign key (loop_run_id) references loop_runs(id),
    foreign key (iteration_id) references loop_iterations(id)
);

create table if not exists resume_events (
    id text primary key,
    pause_id text not null,
    loop_run_id text not null,
    session_id text not null,
    message text not null,
    action text not null,
    created_at text not null,
    metadata_json text not null default '{}',
    foreign key (pause_id) references pause_records(id),
    foreign key (loop_run_id) references loop_runs(id)
);

create table if not exists provider_profiles (
    id text primary key,
    provider text not null,
    label text not null,
    credential_ref text not null,
    status text not null,
    created_at text not null,
    updated_at text not null,
    metadata_json text not null default '{}'
);

create table if not exists provider_runs (
    id text primary key,
    provider text not null,
    provider_profile_id text,
    provider_session_id text,
    session_id text not null,
    loop_run_id text not null,
    iteration_id text not null,
    role text not null,
    status text not null,
    request_json text not null default '{}',
    response_json text not null default '{}',
    error_kind text,
    error_message text,
    created_at text not null,
    completed_at text,
    metadata_json text not null default '{}',
    foreign key (loop_run_id) references loop_runs(id),
    foreign key (iteration_id) references loop_iterations(id)
);

create table if not exists provider_sessions (
    id text primary key,
    provider_profile_id text not null,
    status text not null,
    started_at text not null,
    ended_at text,
    metadata_json text not null default '{}',
    foreign key (provider_profile_id) references provider_profiles(id)
);

create table if not exists quota_state (
    id text primary key,
    provider_profile_id text not null,
    status text not null,
    reason text not null,
    observed_at text not null,
    reset_at text,
    metadata_json text not null default '{}',
    foreign key (provider_profile_id) references provider_profiles(id)
);

create table if not exists context_packages (
    id text primary key,
    session_id text not null,
    loop_run_id text not null,
    iteration_id text,
    role text not null,
    task_id text,
    package_json text not null default '{}',
    created_at text not null,
    metadata_json text not null default '{}',
    foreign key (loop_run_id) references loop_runs(id)
);

create table if not exists memory_entries (
    id text primary key,
    scope text not null,
    role text,
    source_ref text not null,
    summary text not null,
    kind text not null default 'note',
    created_at text not null,
    updated_at text,
    metadata_json text not null default '{}'
);

create table if not exists role_instances (
    id text primary key,
    role text not null,
    label text not null,
    status text not null,
    capabilities_json text not null default '[]',
    current_session_id text,
    current_goal_id text,
    last_used_at text,
    created_at text not null,
    updated_at text not null,
    metadata_json text not null default '{}'
);

create table if not exists role_provider_bindings (
    id text primary key,
    role_instance_id text not null,
    provider_profile_id text not null,
    status text not null,
    created_at text not null,
    updated_at text not null,
    metadata_json text not null default '{}',
    foreign key (role_instance_id) references role_instances(id),
    foreign key (provider_profile_id) references provider_profiles(id)
);

create table if not exists work_items (
    id text primary key,
    session_id text not null,
    goal_id text,
    goal_revision_id text,
    kind text not null,
    required_role text not null,
    title text not null,
    description text not null,
    status text not null,
    priority integer not null default 100,
    created_at text not null,
    updated_at text not null,
    metadata_json text not null default '{}'
);

create table if not exists assignments (
    id text primary key,
    work_item_id text not null,
    role_instance_id text not null,
    session_id text not null,
    goal_id text,
    status text not null,
    assigned_at text not null,
    completed_at text,
    metadata_json text not null default '{}',
    foreign key (work_item_id) references work_items(id),
    foreign key (role_instance_id) references role_instances(id)
);

create table if not exists approval_requests (
    id text primary key,
    session_id text not null,
    kind text not null,
    title text not null,
    description text not null,
    status text not null,
    requested_by text not null,
    scope_json text not null default '{}',
    created_at text not null,
    updated_at text not null,
    metadata_json text not null default '{}'
);

create table if not exists approval_decisions (
    id text primary key,
    approval_request_id text not null,
    decision text not null,
    decided_by text not null,
    message text not null,
    created_at text not null,
    metadata_json text not null default '{}',
    foreign key (approval_request_id) references approval_requests(id)
);

create table if not exists schema_version (
    version integer primary key,
    applied_at text not null
);

create index if not exists idx_memory_entries_scope_role on memory_entries (scope, role);
create index if not exists idx_pause_records_status on pause_records (status);
create index if not exists idx_evidence_refs_run on evidence_refs (loop_run_id);
create index if not exists idx_provider_runs_run on provider_runs (loop_run_id);
create index if not exists idx_loop_decisions_run on loop_decisions (loop_run_id);
create index if not exists idx_goal_revisions_goal on goal_revisions (goal_id);
"""


def phase0_schema_sql() -> str:
    """Return the SQL script for the Phase 0 state schema."""
    return PHASE0_SCHEMA_SQL
