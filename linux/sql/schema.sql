PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    mode TEXT NOT NULL,
    title TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'success', 'failed', 'blocked', 'needs_confirmation')),
    operator_label TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ended_at TEXT,
    retention_class TEXT NOT NULL DEFAULT 'standard',
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS messages (
    message_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('operator', 'assistant', 'system', 'tool')),
    content_redacted TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    redaction_status TEXT NOT NULL DEFAULT 'redacted',
    source_surface TEXT NOT NULL DEFAULT 'unknown',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    parent_task_id TEXT REFERENCES tasks(task_id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    description_redacted TEXT,
    task_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'success', 'failed', 'blocked', 'needs_confirmation')),
    priority INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TEXT,
    ended_at TEXT,
    blocked_reason TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    session_id TEXT REFERENCES sessions(session_id) ON DELETE SET NULL,
    task_id TEXT REFERENCES tasks(task_id) ON DELETE SET NULL,
    event_type TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'info' CHECK (severity IN ('debug', 'info', 'warning', 'error', 'critical')),
    payload_redacted_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    correlation_id TEXT
);

CREATE TABLE IF NOT EXISTS task_edges (
    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    depends_on TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    edge_type TEXT NOT NULL DEFAULT 'requires',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (task_id, depends_on),
    CHECK (task_id <> depends_on)
);

CREATE TRIGGER IF NOT EXISTS task_edges_no_cycle_ai
BEFORE INSERT ON task_edges
BEGIN
    SELECT RAISE(ABORT, 'task_edges self-dependency rejected')
    WHERE NEW.task_id = NEW.depends_on;

    SELECT RAISE(ABORT, 'task_edges cycle rejected')
    WHERE EXISTS (
        WITH RECURSIVE ancestors(node) AS (
            SELECT NEW.depends_on
            UNION
            SELECT task_edges.depends_on
            FROM task_edges
            JOIN ancestors ON task_edges.task_id = ancestors.node
        )
        SELECT 1 FROM ancestors WHERE node = NEW.task_id
    );
END;

CREATE TRIGGER IF NOT EXISTS task_edges_no_cycle_au
BEFORE UPDATE OF task_id, depends_on ON task_edges
BEGIN
    SELECT RAISE(ABORT, 'task_edges self-dependency rejected')
    WHERE NEW.task_id = NEW.depends_on;

    SELECT RAISE(ABORT, 'task_edges cycle rejected')
    WHERE EXISTS (
        WITH RECURSIVE ancestors(node) AS (
            SELECT NEW.depends_on
            UNION
            SELECT task_edges.depends_on
            FROM task_edges
            JOIN ancestors ON task_edges.task_id = ancestors.node
            WHERE NOT (task_edges.task_id = OLD.task_id AND task_edges.depends_on = OLD.depends_on)
        )
        SELECT 1 FROM ancestors WHERE node = NEW.task_id
    );
END;

CREATE TABLE IF NOT EXISTS policy_decisions (
    policy_decision_id TEXT PRIMARY KEY,
    session_id TEXT REFERENCES sessions(session_id) ON DELETE SET NULL,
    task_id TEXT REFERENCES tasks(task_id) ON DELETE SET NULL,
    decision TEXT NOT NULL CHECK (decision IN ('allow', 'deny', 'needs_confirmation')),
    command_class TEXT NOT NULL,
    allowlist_id TEXT,
    requires_confirmation INTEGER NOT NULL DEFAULT 0 CHECK (requires_confirmation IN (0, 1)),
    confirmation_id TEXT,
    reason_redacted TEXT NOT NULL,
    decided_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TEXT,
    CHECK ((requires_confirmation = 0) OR (decision = 'needs_confirmation'))
);

CREATE TABLE IF NOT EXISTS task_runs (
    run_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('pending', 'running', 'success', 'failed', 'blocked', 'needs_confirmation')),
    attempt_number INTEGER NOT NULL CHECK (attempt_number > 0),
    worker_label TEXT,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ended_at TEXT,
    result_summary_redacted TEXT,
    error_redacted TEXT,
    command_log_id TEXT,
    policy_decision_id TEXT REFERENCES policy_decisions(policy_decision_id) ON DELETE SET NULL,
    UNIQUE (task_id, attempt_number)
);

CREATE TABLE IF NOT EXISTS action_confirmations (
    confirmation_id TEXT PRIMARY KEY,
    session_id TEXT REFERENCES sessions(session_id) ON DELETE SET NULL,
    task_id TEXT REFERENCES tasks(task_id) ON DELETE SET NULL,
    policy_decision_id TEXT NOT NULL REFERENCES policy_decisions(policy_decision_id) ON DELETE RESTRICT,
    actor_id TEXT NOT NULL,
    actor_surface TEXT NOT NULL,
    command_class TEXT NOT NULL,
    transport TEXT NOT NULL,
    action_text_redacted TEXT NOT NULL,
    action_hash TEXT NOT NULL,
    arguments_hash TEXT NOT NULL,
    mode_hash TEXT NOT NULL,
    state_binding_hash TEXT NOT NULL,
    allowlist_id TEXT NOT NULL,
    transport_fingerprint TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'confirmed', 'consumed', 'expired', 'rejected', 'invalidated')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TEXT NOT NULL,
    consumed_at TEXT,
    consumed_by_command_log_id TEXT,
    invalidated_reason_redacted TEXT,
    CHECK ((status = 'consumed' AND consumed_at IS NOT NULL) OR (status <> 'consumed')),
    CHECK ((consumed_at IS NULL AND consumed_by_command_log_id IS NULL) OR (consumed_at IS NOT NULL AND consumed_by_command_log_id IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS command_log (
    id INTEGER PRIMARY KEY,
    command_log_id TEXT NOT NULL UNIQUE DEFAULT (lower(hex(randomblob(16)))),
    session_id TEXT REFERENCES sessions(session_id) ON DELETE SET NULL,
    task_id TEXT REFERENCES tasks(task_id) ON DELETE SET NULL,
    transport TEXT NOT NULL,
    command_class TEXT NOT NULL DEFAULT 'unknown',
    command_text_redacted TEXT,
    command_hash TEXT,
    arguments_redacted_json TEXT NOT NULL DEFAULT '{}',
    allowlist_id TEXT,
    confirmation_id TEXT REFERENCES action_confirmations(confirmation_id) ON DELETE RESTRICT,
    policy_decision_id TEXT REFERENCES policy_decisions(policy_decision_id) ON DELETE SET NULL,
    return_code INTEGER,
    stdout_redacted TEXT,
    stdout_hash TEXT,
    stderr_redacted TEXT,
    stderr_hash TEXT,
    result_marker_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TRIGGER IF NOT EXISTS command_log_redaction_guard_ai
BEFORE INSERT ON command_log
BEGIN
    SELECT RAISE(ABORT, 'command_log contains unredacted secret-like value')
    WHERE
        (NEW.command_text_redacted IS NOT NULL AND lower(NEW.command_text_redacted) GLOB '*pwd=*' AND lower(NEW.command_text_redacted) NOT GLOB '*pwd=<redacted>*') OR
        (NEW.stdout_redacted IS NOT NULL AND lower(NEW.stdout_redacted) GLOB '*cookie=*' AND lower(NEW.stdout_redacted) NOT GLOB '*cookie=<redacted>*') OR
        (NEW.stderr_redacted IS NOT NULL AND lower(NEW.stderr_redacted) GLOB '*token=*' AND lower(NEW.stderr_redacted) NOT GLOB '*token=<redacted>*');
END;

CREATE TRIGGER IF NOT EXISTS command_log_redaction_guard_au
BEFORE UPDATE ON command_log
BEGIN
    SELECT RAISE(ABORT, 'command_log contains unredacted secret-like value')
    WHERE
        (NEW.command_text_redacted IS NOT NULL AND lower(NEW.command_text_redacted) GLOB '*pwd=*' AND lower(NEW.command_text_redacted) NOT GLOB '*pwd=<redacted>*') OR
        (NEW.stdout_redacted IS NOT NULL AND lower(NEW.stdout_redacted) GLOB '*cookie=*' AND lower(NEW.stdout_redacted) NOT GLOB '*cookie=<redacted>*') OR
        (NEW.stderr_redacted IS NOT NULL AND lower(NEW.stderr_redacted) GLOB '*token=*' AND lower(NEW.stderr_redacted) NOT GLOB '*token=<redacted>*');
END;

CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id TEXT PRIMARY KEY,
    session_id TEXT REFERENCES sessions(session_id) ON DELETE SET NULL,
    task_id TEXT REFERENCES tasks(task_id) ON DELETE SET NULL,
    artifact_type TEXT NOT NULL,
    storage_uri TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    mime_type TEXT,
    size_bytes INTEGER CHECK (size_bytes IS NULL OR size_bytes >= 0),
    redaction_status TEXT NOT NULL DEFAULT 'redacted',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY,
    document_id TEXT NOT NULL UNIQUE DEFAULT (lower(hex(randomblob(16)))),
    source_id TEXT NOT NULL DEFAULT 'local',
    source_label TEXT NOT NULL DEFAULT 'local',
    source_uri_label TEXT,
    source_path TEXT NOT NULL,
    title TEXT NOT NULL,
    body_redacted TEXT NOT NULL,
    body_hash TEXT NOT NULL,
    version_label TEXT NOT NULL DEFAULT 'v1',
    ingestion_reason TEXT NOT NULL DEFAULT 'operator_requested',
    redaction_status TEXT NOT NULL DEFAULT 'redacted',
    retention_class TEXT NOT NULL DEFAULT 'standard',
    quality_class TEXT NOT NULL DEFAULT 'unknown',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TEXT
);

CREATE TABLE IF NOT EXISTS document_chunks (
    chunk_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL CHECK (chunk_index >= 0),
    text_redacted TEXT NOT NULL,
    text_hash TEXT NOT NULL,
    token_count INTEGER CHECK (token_count IS NULL OR token_count >= 0),
    source_offset_start INTEGER CHECK (source_offset_start IS NULL OR source_offset_start >= 0),
    source_offset_end INTEGER CHECK (source_offset_end IS NULL OR source_offset_end >= 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (document_id, chunk_index)
);

CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
    title,
    body,
    source_path UNINDEXED,
    document_id UNINDEXED
);

CREATE TRIGGER IF NOT EXISTS documents_ai AFTER INSERT ON documents BEGIN
    INSERT INTO documents_fts(rowid, title, body, source_path, document_id)
    VALUES (new.id, new.title, new.body_redacted, new.source_path, new.document_id);
END;

CREATE TRIGGER IF NOT EXISTS documents_ad AFTER DELETE ON documents BEGIN
    DELETE FROM documents_fts WHERE rowid = old.id;
END;

CREATE TRIGGER IF NOT EXISTS documents_au AFTER UPDATE ON documents BEGIN
    DELETE FROM documents_fts WHERE rowid = old.id;
    INSERT INTO documents_fts(rowid, title, body, source_path, document_id)
    VALUES (new.id, new.title, new.body_redacted, new.source_path, new.document_id);
END;

CREATE TABLE IF NOT EXISTS vector_rows (
    vector_id TEXT PRIMARY KEY,
    chunk_id TEXT NOT NULL REFERENCES document_chunks(chunk_id) ON DELETE CASCADE,
    embedding_model TEXT NOT NULL,
    embedding_dimension INTEGER NOT NULL CHECK (embedding_dimension > 0),
    embedding BLOB,
    embedding_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS q_states (
    state_id TEXT PRIMARY KEY,
    session_id TEXT REFERENCES sessions(session_id) ON DELETE SET NULL,
    state_key_hash TEXT NOT NULL UNIQUE,
    state_features_redacted_json TEXT NOT NULL DEFAULT '{}',
    mode TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS q_actions (
    action_id TEXT PRIMARY KEY,
    action_key_hash TEXT NOT NULL UNIQUE,
    action_label TEXT NOT NULL,
    command_class TEXT NOT NULL,
    action_features_redacted_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    disabled_at TEXT
);

CREATE TABLE IF NOT EXISTS rewards (
    reward_id TEXT PRIMARY KEY,
    session_id TEXT REFERENCES sessions(session_id) ON DELETE SET NULL,
    task_id TEXT REFERENCES tasks(task_id) ON DELETE SET NULL,
    state_id TEXT REFERENCES q_states(state_id) ON DELETE SET NULL,
    action_id TEXT REFERENCES q_actions(action_id) ON DELETE SET NULL,
    reward_value REAL NOT NULL,
    reward_source TEXT NOT NULL,
    rationale_redacted TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS q_values (
    state_id TEXT NOT NULL REFERENCES q_states(state_id) ON DELETE CASCADE,
    action_id TEXT NOT NULL REFERENCES q_actions(action_id) ON DELETE CASCADE,
    q_value REAL NOT NULL DEFAULT 0.0,
    visit_count INTEGER NOT NULL DEFAULT 0 CHECK (visit_count >= 0),
    last_reward_id TEXT REFERENCES rewards(reward_id) ON DELETE SET NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (state_id, action_id)
);

CREATE TABLE IF NOT EXISTS session_events (
    id INTEGER PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE DEFAULT (lower(hex(randomblob(16)))),
    player_name TEXT NOT NULL,
    message_redacted TEXT,
    message_hash TEXT,
    source_surface TEXT NOT NULL DEFAULT 'kolmafia-session-log',
    provenance_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS session_listener_cursors (
    cursor_id TEXT PRIMARY KEY,
    player_name TEXT NOT NULL,
    source_path TEXT NOT NULL,
    file_device INTEGER,
    file_inode INTEGER,
    file_mtime_ns INTEGER,
    byte_offset INTEGER NOT NULL DEFAULT 0 CHECK (byte_offset >= 0),
    file_size INTEGER NOT NULL DEFAULT 0 CHECK (file_size >= 0),
    rotation_state TEXT NOT NULL DEFAULT 'initialized' CHECK (rotation_state IN ('initialized', 'steady', 'missing', 'rotated', 'truncated')),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (player_name, source_path)
);

CREATE TABLE IF NOT EXISTS capability_records (
    entry_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    entry_type TEXT NOT NULL,
    language TEXT NOT NULL,
    signature_or_syntax TEXT,
    aliases TEXT NOT NULL DEFAULT '',
    source_document TEXT NOT NULL,
    source_location TEXT NOT NULL,
    evidence_status TEXT NOT NULL,
    read_or_mutate TEXT NOT NULL,
    argument_dependent INTEGER NOT NULL DEFAULT 0 CHECK (argument_dependent IN (0, 1)),
    domains_touched TEXT NOT NULL DEFAULT '',
    reads_game_state INTEGER NOT NULL DEFAULT 0 CHECK (reads_game_state IN (0, 1)),
    mutates_game_state INTEGER NOT NULL DEFAULT 0 CHECK (mutates_game_state IN (0, 1)),
    reads_preferences INTEGER NOT NULL DEFAULT 0 CHECK (reads_preferences IN (0, 1)),
    writes_preferences INTEGER NOT NULL DEFAULT 0 CHECK (writes_preferences IN (0, 1)),
    reads_files INTEGER NOT NULL DEFAULT 0 CHECK (reads_files IN (0, 1)),
    writes_files INTEGER NOT NULL DEFAULT 0 CHECK (writes_files IN (0, 1)),
    contacts_network INTEGER NOT NULL DEFAULT 0 CHECK (contacts_network IN (0, 1)),
    spends_turns INTEGER NOT NULL DEFAULT 0 CHECK (spends_turns IN (0, 1)),
    spends_meat INTEGER NOT NULL DEFAULT 0 CHECK (spends_meat IN (0, 1)),
    spends_items INTEGER NOT NULL DEFAULT 0 CHECK (spends_items IN (0, 1)),
    changes_inventory INTEGER NOT NULL DEFAULT 0 CHECK (changes_inventory IN (0, 1)),
    changes_equipment INTEGER NOT NULL DEFAULT 0 CHECK (changes_equipment IN (0, 1)),
    changes_choice_state INTEGER NOT NULL DEFAULT 0 CHECK (changes_choice_state IN (0, 1)),
    social_or_kmail_output INTEGER NOT NULL DEFAULT 0 CHECK (social_or_kmail_output IN (0, 1)),
    authentication_effect INTEGER NOT NULL DEFAULT 0 CHECK (authentication_effect IN (0, 1)),
    process_or_ui_effect INTEGER NOT NULL DEFAULT 0 CHECK (process_or_ui_effect IN (0, 1)),
    nested_cli_execution INTEGER NOT NULL DEFAULT 0 CHECK (nested_cli_execution IN (0, 1)),
    nested_ash_execution INTEGER NOT NULL DEFAULT 0 CHECK (nested_ash_execution IN (0, 1)),
    script_execution INTEGER NOT NULL DEFAULT 0 CHECK (script_execution IN (0, 1)),
    deferred_execution INTEGER NOT NULL DEFAULT 0 CHECK (deferred_execution IN (0, 1)),
    hook_or_lifecycle_surface INTEGER NOT NULL DEFAULT 0 CHECK (hook_or_lifecycle_surface IN (0, 1)),
    relay_or_url_surface INTEGER NOT NULL DEFAULT 0 CHECK (relay_or_url_surface IN (0, 1)),
    candidate_risk TEXT NOT NULL DEFAULT 'unknown',
    recursive_classification_required INTEGER NOT NULL DEFAULT 0 CHECK (recursive_classification_required IN (0, 1)),
    fail_closed_if_unresolved INTEGER NOT NULL DEFAULT 0 CHECK (fail_closed_if_unresolved IN (0, 1)),
    native_or_runtime_surface TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    source_corpus TEXT NOT NULL,
    source_row_number INTEGER NOT NULL CHECK (source_row_number > 0),
    source_content_hash TEXT NOT NULL,
    provenance_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (source_corpus IN ('kolmafia_capability_index.csv', 'kolmafia_priority_flags.csv'))
);

CREATE TABLE IF NOT EXISTS capability_priority_annotations (
    entry_id TEXT PRIMARY KEY REFERENCES capability_records(entry_id) ON DELETE CASCADE,
    priority_candidate_risk TEXT NOT NULL DEFAULT 'unknown',
    priority_recursive_classification_required INTEGER NOT NULL DEFAULT 0 CHECK (priority_recursive_classification_required IN (0, 1)),
    priority_fail_closed_if_unresolved INTEGER NOT NULL DEFAULT 0 CHECK (priority_fail_closed_if_unresolved IN (0, 1)),
    priority_read_or_mutate TEXT NOT NULL DEFAULT 'unknown',
    priority_domains_touched TEXT NOT NULL DEFAULT '',
    annotation_json TEXT NOT NULL DEFAULT '{}',
    source_corpus TEXT NOT NULL DEFAULT 'kolmafia_priority_flags.csv' CHECK (source_corpus = 'kolmafia_priority_flags.csv'),
    source_row_number INTEGER NOT NULL CHECK (source_row_number > 0),
    source_content_hash TEXT NOT NULL,
    provenance_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS agent_resource_records (
    resource_id TEXT PRIMARY KEY,
    capability_entry_id TEXT REFERENCES capability_records(entry_id) ON DELETE SET NULL,
    resource_kind TEXT NOT NULL,
    resource_name TEXT NOT NULL,
    access_mode TEXT NOT NULL CHECK (access_mode IN ('read', 'write', 'mutate', 'execute', 'contact', 'spend', 'unknown')),
    authority_surface TEXT NOT NULL DEFAULT 'kolmafia',
    source_corpus TEXT NOT NULL,
    source_entry_id TEXT NOT NULL,
    source_row_number INTEGER NOT NULL CHECK (source_row_number > 0),
    source_content_hash TEXT NOT NULL,
    provenance_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (source_corpus IN ('kolmafia_capability_index.csv', 'kolmafia_priority_flags.csv'))
);

CREATE TABLE IF NOT EXISTS source_catalog (
    source_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    source_name TEXT NOT NULL DEFAULT '',
    source_uri TEXT,
    source_path TEXT,
    source_category TEXT NOT NULL,
    stack_language TEXT NOT NULL DEFAULT '',
    kol_relevance TEXT NOT NULL DEFAULT 'unknown',
    trust_level TEXT NOT NULL DEFAULT 'unknown',
    source_load_status TEXT NOT NULL DEFAULT 'declared' CHECK (source_load_status IN ('declared', 'loaded', 'conflict', 'rejected')),
    load_manifest_id TEXT NOT NULL DEFAULT '',
    source_version TEXT NOT NULL DEFAULT '',
    source_content_hash TEXT NOT NULL DEFAULT '',
    source_metadata_hash TEXT NOT NULL DEFAULT '',
    provenance_json TEXT NOT NULL DEFAULT '{}',
    local_only INTEGER NOT NULL DEFAULT 0 CHECK (local_only IN (0, 1)),
    publishable INTEGER NOT NULL DEFAULT 0 CHECK (publishable IN (0, 1)),
    recommendation TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS source_crosswalk (
    crosswalk_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES source_catalog(source_id) ON DELETE CASCADE,
    source_content_hash TEXT NOT NULL DEFAULT '',
    graph_category TEXT NOT NULL CHECK (graph_category IN ('GAMEPLAY', 'AGENT_STACK', 'KNOWLEDGE_BASE')),
    graph_node_key TEXT NOT NULL,
    relationship TEXT NOT NULL,
    confidence TEXT NOT NULL DEFAULT 'unknown',
    evidence_content_hash TEXT NOT NULL DEFAULT '',
    provenance_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (source_id, graph_category, graph_node_key, relationship)
);

CREATE TRIGGER IF NOT EXISTS session_events_redaction_guard_ai
BEFORE INSERT ON session_events
BEGIN
    SELECT RAISE(ABORT, 'session_events contains unredacted secret-like value')
    WHERE
        (NEW.message_redacted IS NOT NULL AND lower(NEW.message_redacted) GLOB '*token=*' AND lower(NEW.message_redacted) NOT GLOB '*token=<redacted>*');
END;

CREATE INDEX IF NOT EXISTS idx_messages_session_created ON messages(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_events_session_created ON events(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_events_task_created ON events(task_id, created_at);
CREATE INDEX IF NOT EXISTS idx_tasks_session_status ON tasks(session_id, status, priority, created_at);
CREATE INDEX IF NOT EXISTS idx_tasks_parent ON tasks(parent_task_id);
CREATE INDEX IF NOT EXISTS idx_task_edges_depends_on ON task_edges(depends_on);
CREATE INDEX IF NOT EXISTS idx_task_runs_task_attempt ON task_runs(task_id, attempt_number);
CREATE INDEX IF NOT EXISTS idx_policy_session_decision ON policy_decisions(session_id, decision, decided_at);
CREATE INDEX IF NOT EXISTS idx_confirmations_exact_action ON action_confirmations(actor_id, action_hash, arguments_hash, state_binding_hash, status, expires_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_command_log_confirmation_one_shot ON command_log(confirmation_id) WHERE confirmation_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_command_log_session_created ON command_log(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_artifacts_session ON artifacts(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_documents_source ON documents(source_id, source_label, deleted_at);
CREATE INDEX IF NOT EXISTS idx_documents_body_hash ON documents(body_hash);
CREATE INDEX IF NOT EXISTS idx_chunks_document ON document_chunks(document_id, chunk_index);
CREATE INDEX IF NOT EXISTS idx_chunks_text_hash ON document_chunks(text_hash);
CREATE INDEX IF NOT EXISTS idx_vector_rows_chunk ON vector_rows(chunk_id);
CREATE INDEX IF NOT EXISTS idx_q_states_session ON q_states(session_id, mode);
CREATE INDEX IF NOT EXISTS idx_q_values_action ON q_values(action_id, updated_at);
CREATE INDEX IF NOT EXISTS idx_rewards_session ON rewards(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_session_events_player_created ON session_events(player_name, created_at);
CREATE INDEX IF NOT EXISTS idx_session_listener_cursors_player ON session_listener_cursors(player_name, updated_at);
CREATE INDEX IF NOT EXISTS idx_capability_records_name_type ON capability_records(name, entry_type, language);
CREATE INDEX IF NOT EXISTS idx_capability_records_risk ON capability_records(candidate_risk, fail_closed_if_unresolved, recursive_classification_required);
CREATE INDEX IF NOT EXISTS idx_capability_priority_annotations_risk ON capability_priority_annotations(priority_candidate_risk, priority_fail_closed_if_unresolved, priority_recursive_classification_required);
CREATE INDEX IF NOT EXISTS idx_agent_resource_records_capability ON agent_resource_records(capability_entry_id);
CREATE INDEX IF NOT EXISTS idx_agent_resource_records_lookup ON agent_resource_records(resource_kind, resource_name, access_mode);
CREATE INDEX IF NOT EXISTS idx_agent_resource_records_source ON agent_resource_records(source_corpus, source_entry_id, source_row_number);
CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_resource_records_resource_source ON agent_resource_records(resource_kind, resource_name, access_mode, source_entry_id);
CREATE INDEX IF NOT EXISTS idx_source_catalog_category ON source_catalog(source_category, stack_language);
CREATE INDEX IF NOT EXISTS idx_source_catalog_publishability ON source_catalog(local_only, publishable);
CREATE INDEX IF NOT EXISTS idx_source_catalog_conflict_lookup ON source_catalog(source_name, source_uri, source_path, source_content_hash);
CREATE UNIQUE INDEX IF NOT EXISTS uq_source_catalog_loaded_identity_content
ON source_catalog(source_name, COALESCE(source_uri, ''), COALESCE(source_path, ''), source_content_hash)
WHERE source_content_hash <> '';
CREATE INDEX IF NOT EXISTS idx_source_crosswalk_source ON source_crosswalk(source_id);
CREATE INDEX IF NOT EXISTS idx_source_crosswalk_graph ON source_crosswalk(graph_category, graph_node_key);
CREATE INDEX IF NOT EXISTS idx_source_crosswalk_source_content ON source_crosswalk(source_id, source_content_hash);
