// Resolve only exact, unambiguous regional names from authenticated request metadata.
const regionalInput = $('Webhook').first().json.body;
const regionalCodes = [...new Set((Array.isArray(regionalInput.allowed_regionals)
  ? regionalInput.allowed_regionals : []).filter(code => typeof code === 'string' && code.trim()))];
const regionalKey = value => String(value ?? '').normalize('NFD')
  .replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/^reg[\s_-]+/, '')
  .replace(/[^a-z0-9]+/g, ' ').trim();
const regionalMessage = ' ' + regionalKey(regionalInput.message) + ' ';
const regionalMentions = regionalCodes.filter(code => {
  const key = regionalKey(code);
  return key && regionalMessage.includes(' ' + key + ' ');
});
if (regionalMentions.length === 1) {
  const code = regionalMentions[0];
  // An omitted filter is grounded in the current request, not in model memory.
  if (!plan.regional) plan.regional = code;
  if (regionalKey(plan.regional) === regionalKey(code)
      && plan.search && regionalKey(plan.search) === regionalKey(code)) {
    plan.search = '';
  }
}
