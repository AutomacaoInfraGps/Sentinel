// Executed as an n8n Set expression. The model provides data, never executable code.
const response = $json;
if (response.done !== true || response.done_reason === 'length') {
    throw new Error('O modelo não concluiu um plano válido.');
}
const plan = JSON.parse(response.message.content);
const schema = SCHEMA_PLACEHOLDER;
if (!plan || typeof plan !== 'object' || Array.isArray(plan)) {
    throw new Error('Plano inválido.');
}
for (const key of Object.keys(plan)) {
    if (!Object.hasOwn(schema.properties, key)) throw new Error('Campo de plano inválido.');
}
for (const key of schema.required) {
    const rule = schema.properties[key];
    const value = plan[key];
    if (rule.type === 'array') {
        if (!Array.isArray(value) || value.length > rule.maxItems ||
                value.some(item => !rule.items.enum.includes(item))) throw new Error('Campos inválidos.');
    } else if (rule.type === 'integer') {
        if (!Number.isInteger(value) || value < rule.minimum || value > rule.maximum) {
            throw new Error('Paginação inválida.');
        }
    } else if (typeof value !== 'string' || value.length > (rule.maxLength ?? 120) ||
            (rule.enum && !rule.enum.includes(value))) {
        throw new Error('Valor de plano inválido.');
    }
}
if (plan.mode === 'query') {
    if (!plan.resource || plan.reply) throw new Error('Consulta inválida.');
} else if (plan.resource || plan.regional || plan.status || plan.search || !plan.reply.trim()) {
    throw new Error('Resposta social ou esclarecimento inválido.');
}
return plan;
