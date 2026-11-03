'use strict';

/**
 * Desktop-side model license gate. Mirrors the policy semantics in
 * services/licensing/policy.py, but stays dependency-free so it can run in the
 * Electron main process before any network or model operation.
 */
const fs = require('node:fs');
const path = require('node:path');

const DEFAULT_POLICY = path.resolve(__dirname, '../../security/model-policy.json');
const USES = Object.freeze(['inference', 'training', 'redistribution', 'shipping']);

function policyPath({ packaged = false, resourcesPath = '' } = {}) {
  return packaged ? path.join(resourcesPath, 'model-policy.json') : DEFAULT_POLICY;
}

function loadPolicy(file = DEFAULT_POLICY) {
  const parsed = JSON.parse(fs.readFileSync(file, 'utf8'));
  if (!parsed || typeof parsed !== 'object' || !Array.isArray(parsed.models)) {
    throw new Error('Model license policy is malformed');
  }
  return parsed;
}

function normalize(value) {
  return String(value ?? '').trim().toLowerCase();
}

function checkModel({ modelId, license, use = 'inference' } = {}, policy = loadPolicy()) {
  if (!USES.includes(use)) throw new TypeError(`Unknown model use: ${use}`);
  const wanted = normalize(modelId);
  if (!wanted) {
    return {
      approved: false,
      status: 'missing',
      use,
      model_id: '',
      license: license ?? '',
      reason: 'A reviewed model id is required',
      requirements: []
    };
  }
  const model = (policy.models || []).find(candidate => {
    const names = [candidate.id, ...(candidate.aliases || [])];
    return names.some(name => normalize(name) === wanted);
  });
  if (!model) {
    return {
      approved: false,
      status: 'unapproved',
      use,
      model_id: String(modelId),
      license: String(license ?? ''),
      reason: 'Model is not in the reviewed registry (security/model-policy.json)',
      requirements: []
    };
  }
  const registered = String(model.license || '');
  if (!license || normalize(license) !== normalize(registered)) {
    return {
      approved: false,
      status: 'mismatch',
      use,
      model_id: model.id,
      license: String(license ?? ''),
      reason: `Supplied license does not match the reviewed value (${registered})`,
      requirements: [...(model.requirements || [])]
    };
  }
  const allowed = policy.allowed_license_ids || [];
  const custom = (policy.custom_licenses || {})[registered];
  if (!allowed.includes(registered) && !(custom && custom.reviewed === true)) {
    return {
      approved: false,
      status: 'unapproved',
      use,
      model_id: model.id,
      license: registered,
      reason: 'License is neither allowlisted nor a reviewed custom license',
      requirements: [...(model.requirements || [])]
    };
  }
  if (!model.uses || model.uses[use] !== true) {
    return {
      approved: false,
      status: 'restricted',
      use,
      model_id: model.id,
      license: registered,
      reason: `The reviewed license does not permit '${use}' in this project`,
      requirements: [...(model.requirements || [])]
    };
  }
  return {
    approved: true,
    status: 'approved',
    use,
    model_id: model.id,
    license: registered,
    license_url: model.license_url,
    reason: 'Model and license are approved for this use',
    requirements: [...(model.requirements || [])]
  };
}

module.exports = { DEFAULT_POLICY, USES, policyPath, loadPolicy, checkModel };
