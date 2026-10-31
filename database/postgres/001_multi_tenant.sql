-- Reference PostgreSQL schema for future hosted multi-user deployment.
-- Not wired into the single-user desktop app.
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE TABLE IF NOT EXISTS organizations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS organization_members (
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  user_id UUID NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('owner','admin','developer','viewer')),
  PRIMARY KEY (organization_id,user_id)
);
CREATE TABLE IF NOT EXISTS projects (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  slug TEXT NOT NULL,
  title TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(organization_id,slug),
  UNIQUE(id,organization_id)
);
CREATE INDEX IF NOT EXISTS projects_org_recent_idx ON projects(organization_id,updated_at DESC);
CREATE TABLE IF NOT EXISTS agent_jobs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL,
  project_id UUID NOT NULL,
  idempotency_key TEXT NOT NULL,
  kind TEXT NOT NULL,
  state TEXT NOT NULL DEFAULT 'queued' CHECK (state IN ('queued','leased','completed','failed','cancelled')),
  priority SMALLINT NOT NULL DEFAULT 0,
  attempts INT NOT NULL DEFAULT 0,
  max_attempts INT NOT NULL DEFAULT 3,
  lease_until TIMESTAMPTZ,
  available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  payload JSONB NOT NULL,
  result JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  FOREIGN KEY(project_id,organization_id) REFERENCES projects(id,organization_id) ON DELETE CASCADE,
  UNIQUE(organization_id,idempotency_key)
);
CREATE INDEX IF NOT EXISTS agent_jobs_claim_idx ON agent_jobs(priority DESC,available_at,created_at) WHERE state='queued';
CREATE INDEX IF NOT EXISTS agent_jobs_org_project_idx ON agent_jobs(organization_id,project_id,created_at DESC);
CREATE TABLE IF NOT EXISTS audit_events (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  organization_id UUID NOT NULL REFERENCES organizations(id),
  actor_id UUID,
  project_id UUID,
  event_type TEXT NOT NULL,
  details JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS audit_events_org_time_idx ON audit_events(organization_id,created_at DESC,id DESC);
ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE projects FORCE ROW LEVEL SECURITY;
ALTER TABLE agent_jobs FORCE ROW LEVEL SECURITY;
ALTER TABLE audit_events FORCE ROW LEVEL SECURITY;
-- The application MUST set app.organization_id transaction-locally after verifying membership.
-- Never grant BYPASSRLS or table-owner privileges to the application role.
CREATE POLICY projects_tenant ON projects USING (organization_id = nullif(current_setting('app.organization_id',true),'')::uuid)
 WITH CHECK (organization_id = nullif(current_setting('app.organization_id',true),'')::uuid);
CREATE POLICY jobs_tenant ON agent_jobs USING (organization_id = nullif(current_setting('app.organization_id',true),'')::uuid)
 WITH CHECK (organization_id = nullif(current_setting('app.organization_id',true),'')::uuid);
CREATE POLICY audit_tenant ON audit_events USING (organization_id = nullif(current_setting('app.organization_id',true),'')::uuid)
 WITH CHECK (organization_id = nullif(current_setting('app.organization_id',true),'')::uuid);
-- Atomic leasing pattern for a dedicated queue worker; execute inside a transaction
-- after verified tenant scoping. Retries, heartbeat and dead-letter handling still needed.
-- SELECT id FROM agent_jobs WHERE state='queued' AND available_at<=now()
-- ORDER BY priority DESC,created_at FOR UPDATE SKIP LOCKED LIMIT 1;
