-- Phase H3: Agent Memory system
-- Persistent cross-session memory keyed by (scope, scope_id, key).

CREATE TABLE IF NOT EXISTS agent_memories (
    id               SERIAL PRIMARY KEY,
    scope            VARCHAR(20)  NOT NULL,         -- 'global' | 'user' | 'project'
    scope_id         INT          NULL,             -- user_id / project_id; NULL for global
    key              VARCHAR(100) NOT NULL,
    content          TEXT         NOT NULL,
    tags             VARCHAR(500) NULL,             -- comma-separated
    importance       INT          NOT NULL DEFAULT 3,  -- 1..5, higher = more important
    created_by_agent VARCHAR(100) NULL,
    created_at       VARCHAR(50)  NOT NULL,
    updated_at       VARCHAR(50)  NOT NULL,
    last_accessed_at VARCHAR(50)  NULL,
    accessed_count   INT          NOT NULL DEFAULT 0,
    CONSTRAINT uq_memory_scope_key UNIQUE (scope, scope_id, key)
);

CREATE INDEX IF NOT EXISTS idx_memory_scope
    ON agent_memories (scope, scope_id);
CREATE INDEX IF NOT EXISTS idx_memory_scope_importance
    ON agent_memories (scope, scope_id, importance);
