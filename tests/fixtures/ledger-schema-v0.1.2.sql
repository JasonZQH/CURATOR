-- Schema of a ledger created by the released v0.1.2, captured from a real run.
-- Committed as SQL rather than a .sqlite file: the CI guard rightly refuses binary
-- ledgers, and a text dump is the part a reviewer can actually read.
-- Regenerate with a v0.1.2 worktree; never hand-edit to match a newer schema.

CREATE TABLE approval_decisions (
    id text primary key,
    approval_request_id text not null,
    decision text not null,
    decided_by text not null,
    message text not null,
    created_at text not null,
    metadata_json text not null default '{}',
    foreign key (approval_request_id) references approval_requests(id)
);
CREATE TABLE approval_requests (
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
CREATE TABLE assignments (
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
CREATE TABLE context_packages (
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
CREATE TABLE discovery_sessions (
    id text primary key,
    project_root text not null,
    status text not null,
    goal_id text,
    created_at text not null,
    updated_at text not null,
    metadata_json text not null default '{}'
);
CREATE TABLE discussion_turns (
    id text primary key,
    discovery_session_id text not null,
    role text not null,
    content text not null,
    created_at text not null,
    metadata_json text not null default '{}',
    foreign key (discovery_session_id) references discovery_sessions(id)
);
CREATE TABLE events (
    id text primary key,
    session_id text not null,
    task_id text,
    type text not null,
    created_at text not null,
    payload_json text not null default '{}',
    foreign key (session_id) references sessions(id),
    foreign key (task_id) references tasks(id)
);
CREATE TABLE evidence_refs (
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
CREATE TABLE goal_drafts (
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
CREATE TABLE goal_revisions (
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
CREATE TABLE goal_runs (
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
CREATE TABLE goals (
    id text primary key,
    source_request text not null,
    summary text not null,
    status text not null,
    current_revision_id text,
    created_at text not null,
    updated_at text not null,
    metadata_json text not null default '{}'
);
CREATE TABLE loop_decisions (
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
CREATE TABLE loop_iterations (
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
CREATE TABLE loop_runs (
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
CREATE TABLE memory_entries (
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
CREATE TABLE messages (
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
CREATE TABLE pause_records (
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
CREATE TABLE provider_profiles (
    id text primary key,
    provider text not null,
    label text not null,
    credential_ref text not null,
    status text not null,
    created_at text not null,
    updated_at text not null,
    metadata_json text not null default '{}'
);
CREATE TABLE provider_runs (
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
CREATE TABLE provider_sessions (
    id text primary key,
    provider_profile_id text not null,
    status text not null,
    started_at text not null,
    ended_at text,
    metadata_json text not null default '{}',
    foreign key (provider_profile_id) references provider_profiles(id)
);
CREATE TABLE quota_state (
    id text primary key,
    provider_profile_id text not null,
    status text not null,
    reason text not null,
    observed_at text not null,
    reset_at text,
    metadata_json text not null default '{}',
    foreign key (provider_profile_id) references provider_profiles(id)
);
CREATE TABLE resume_events (
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
CREATE TABLE role_instances (
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
CREATE TABLE role_provider_bindings (
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
CREATE TABLE role_selections (
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
CREATE TABLE schema_version (
    version integer primary key,
    applied_at text not null
);
CREATE TABLE sessions (
    id text primary key,
    project_root text not null,
    mode text not null,
    status text not null,
    created_at text not null,
    updated_at text not null,
    metadata_json text not null default '{}'
);
CREATE TABLE tasks (
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
CREATE TABLE work_items (
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
CREATE INDEX idx_evidence_refs_run on evidence_refs (loop_run_id);
CREATE INDEX idx_goal_revisions_goal on goal_revisions (goal_id);
CREATE INDEX idx_loop_decisions_run on loop_decisions (loop_run_id);
CREATE INDEX idx_memory_entries_scope_role on memory_entries (scope, role);
CREATE INDEX idx_pause_records_status on pause_records (status);
CREATE INDEX idx_provider_runs_run on provider_runs (loop_run_id);

insert into schema_version (version, applied_at) values (1, '2026-08-17T20:12:03.652583+00:00');
insert into schema_version (version, applied_at) values (2, '2026-08-17T20:12:03.652791+00:00');
