-- Example atomic job lease claim for one tenant.
-- Use a transaction; parameter $1 is the tenant ID.
WITH next_job AS (
 SELECT id FROM jobs
 WHERE organization_id=$1 AND state='queued' AND available_at<=now()
 ORDER BY available_at,id
 FOR UPDATE SKIP LOCKED LIMIT 1
)
UPDATE jobs AS j
SET state='leased', attempts=j.attempts+1,
 lease_until=now()+interval '2 minutes', updated_at=now()
FROM next_job
WHERE j.id=next_job.id
RETURNING j.*;
