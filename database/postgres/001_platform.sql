-- PostgreSQL 16+ production-oriented schema foundation.
-- Run only against a database you own; no automatic deployment.
BEGIN;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE TABLE IF NOT EXISTS organizations (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 name text NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS users (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 email text NOT NULL UNIQUE,
 password_hash text,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS memberships (
 organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
 user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 role text NOT NULL CHECK(role IN ('owner','admin','member','viewer')),
 PRIMARY KEY (organization_id,user_id)
);
CREATE TABLE IF NOT EXISTS projects (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
 name text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(organization_id,name),
 UNIQUE(organization_id,id)
);
CREATE TABLE IF NOT EXISTS conversations (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 organization_id uuid NOT NULL,
 project_id uuid NOT NULL,
 created_by uuid NOT NULL REFERENCES users(id),
 created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(organization_id,project_id) REFERENCES projects(organization_id,id) ON DELETE CASCADE,
 UNIQUE(organization_id,id)
);
CREATE TABLE IF NOT EXISTS messages (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 organization_id uuid NOT NULL,
 conversation_id uuid NOT NULL,
 role text NOT NULL CHECK(role IN ('system','user','assistant','tool')),
 content text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(organization_id,conversation_id) REFERENCES conversations(organization_id,id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_messages_timeline ON messages(organization_id,conversation_id,created_at DESC,id DESC);
CREATE TABLE IF NOT EXISTS jobs (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 organization_id uuid NOT NULL,
 project_id uuid NOT NULL,
 requested_by uuid NOT NULL REFERENCES users(id),
 kind text NOT NULL,
 state text NOT NULL DEFAULT 'queued' CHECK(state IN ('queued','leased','succeeded','failed','cancelled')),
 attempts int NOT NULL DEFAULT 0 CHECK(attempts>=0),
 available_at timestamptz NOT NULL DEFAULT now(),
 lease_until timestamptz,
 idempotency_key text NOT NULL,
 payload jsonb NOT NULL DEFAULT '{}'::jsonb,
 result jsonb,
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(organization_id,project_id) REFERENCES projects(organization_id,id) ON DELETE CASCADE,
 UNIQUE(organization_id,idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_jobs_queue ON jobs(available_at,id) WHERE state='queued';
CREATE INDEX IF NOT EXISTS idx_jobs_lease ON jobs(lease_until) WHERE state='leased';
CREATE TABLE IF NOT EXISTS approvals (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 organization_id uuid NOT NULL,
 job_id uuid NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
 actor_id uuid REFERENCES users(id),
 action text NOT NULL,
 status text NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected','expired')),
 payload_sha256 text NOT NULL CHECK(payload_sha256 ~ '^[a-f0-9]{64}$'),
 created_at timestamptz NOT NULL DEFAULT now(),
 resolved_at timestamptz
);
CREATE INDEX IF NOT EXISTS idx_approvals_pending ON approvals(organization_id,created_at) WHERE status='pending';
CREATE TABLE IF NOT EXISTS audit_events (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 organization_id uuid NOT NULL,
 actor_id uuid,
 event_type text NOT NULL,
 resource_id text,
 metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_audit_tenant_time ON audit_events(organization_id,created_at DESC,id DESC);
COMMIT;
