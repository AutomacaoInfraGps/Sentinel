const response = $json;
if (response.done !== true || response.done_reason === 'length') {
    throw new Error('O modelo não concluiu um plano válido.');
}
let plan = JSON.parse(response.message.content);
const allowedValues = ENUMS_PLACEHOLDER;
const allowedFields = FIELDS_PLACEHOLDER;
const required = ['mode', 'reply', 'resource', 'regional', 'status', 'search', 'view', 'fields', 'limit', 'offset'];
if (!plan || typeof plan !== 'object' || Array.isArray(plan)) {
    throw new Error('Plano inválido.');
}
if (Object.hasOwn(plan, 'query')) {
    if (plan.mode !== 'query' || Object.keys(plan).some(key => !['mode', 'query'].includes(key)) ||
            !plan.query || typeof plan.query !== 'object' || Array.isArray(plan.query) ||
            Object.keys(plan.query).some(key => !required.includes(key) || ['mode', 'reply'].includes(key))) {
        throw new Error('Consulta inválida.');
    }
    plan = {...plan.query, mode: 'query', reply: ''};
} else if (plan.mode !== 'query' && Object.keys(plan).every(key => ['mode', 'reply'].includes(key))) {
    plan = {resource: '', regional: '', status: '', search: '', view: 'list', fields: [],
            limit: 20, offset: 0, ...plan};
}
for (const key of Object.keys(plan)) {
    if (!required.includes(key)) throw new Error('Campo de plano inválido.');
}
for (const key of required) {
    const value = plan[key];
    if (key === 'fields') {
        if (!Array.isArray(value) || value.length > 8 ||
                value.some(item => !allowedFields.includes(item))) throw new Error('Campos inválidos.');
    } else if (key === 'limit' || key === 'offset') {
        const minimum = key === 'limit' ? 1 : 0;
        const maximum = key === 'limit' ? 50 : 10000;
        if (!Number.isInteger(value) || value < minimum || value > maximum) {
            throw new Error('Paginação inválida.');
        }
    } else if (typeof value !== 'string' || value.length > (key === 'reply' ? 500 : 120) ||
            (allowedValues[key] && !allowedValues[key].includes(value))) {
        throw new Error('Valor de plano inválido.');
    }
}
if (plan.mode === 'query') {
    if (!plan.resource || plan.reply) throw new Error('Consulta inválida.');
    const input = $('Webhook').first().json.body ?? {};
    const context = $('Ler contexto curto').first().json.context;
    const normalize = value => String(value || '').normalize('NFD')
        .replace(/[\u0300-\u036f]/g, '').toLowerCase()
        .replace(/[^a-z0-9]+/g, ' ').trim().replace(/^reg\s+/, '');
    const regional = normalize(plan.regional);
    const message = ' ' + normalize(input.message) + ' ';
    const previousRegional = normalize(context?.previous_query?.regional);
    if (regional && !message.includes(' ' + regional + ' ') && regional !== previousRegional) {
        plan.regional = '';
    }
} else {
    if (plan.resource || !plan.reply.trim()) {
        throw new Error('Resposta social ou esclarecimento inválido.');
    }
    plan.regional = '';
    plan.status = '';
    plan.search = '';
    plan.fields = [];
}
return plan;
