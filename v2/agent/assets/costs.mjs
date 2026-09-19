/** @typedef {{start: string, end_exclusive: string}} Period */
/** @typedef {{usd: string, label: string}} Amount */
/** @typedef {{aws: string | null, openai: string | null, total: string | null}} Totals */
/** @typedef {Totals & {date: string}} Day */
/** @typedef {{status: string, scope: string, currency: string, requested: Period, retrieved_at: string, finalized_through: null, estimated: boolean | null, daily: {date: string, usd: string}[], aws_services: Amount[], aws_environments: Amount[]}} Source */
/** @typedef {{schema_version: number, kind: string, environment: string, scope: string, currency: string, periods: Record<string, Period>, requested: Period, published_at: string, attempt: {at: string, status: string, sources: Record<string, string>}, sources: Record<string, Source>, month_to_date: Totals, daily: Day[], aws_services: Amount[], aws_environments: Amount[]}} Snapshot */
/** @param {string} id */
const $ = (id) => /** @type {HTMLElement} */ (document.getElementById(id));
/** @param {string} id @param {string} value */
const set = (id, value) => { $(id).textContent = value; };
const expectedEnvironment = /** @type {HTMLMetaElement} */ (document.querySelector('meta[name="cost-environment"]')).content;
/** @type {Record<string, string>} */
const names = { aws_production: 'AWS production account', aws_development: 'AWS development account', openai: 'OpenAI organization' };
/** @type {Record<string, string>} */
const colors = { production: '#175ccd', development: '#7093c7', shared: '#102746', unallocated: '#b8893a' };
/** @type {Record<string, string>} */
const scopes = { aws_production: 'production-account', aws_development: 'development-account', openai: 'organization' };
/** @param {unknown} value */
const require = (value) => { if (!value) throw new Error('Invalid billing snapshot'); };
/** @param {unknown} value @param {string} fields */
const keys = (value, fields) => require(value && typeof value === 'object' && !Array.isArray(value) && Object.keys(value).sort().join(' ') === fields.split(' ').sort().join(' '));
/** @param {string} value */
const units = (value) => {
  require(typeof value === 'string' && /^-?(0|[1-9]\d{0,17})(\.\d{1,30})?$/.test(value));
  const [whole, fraction = ''] = value.replace('-', '').split('.');
  return BigInt(whole + fraction.padEnd(30, '0')) * (value.startsWith('-') ? -1n : 1n);
};
/** @param {string[]} values */
const sum = (values) => values.reduce((result, value) => result + units(value), 0n);
/** @param {string | null} value @param {bigint | null | undefined} expected */
const matches = (value, expected) => require(expected === null ? value === null : units(/** @type {string} */ (value)) === expected);
/** @param {string} value */
const instant = (value) => {
  require(typeof value === 'string' && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(value));
  const result = Date.parse(value);
  require(Number.isFinite(result) && new Date(result).toISOString() === value.replace('Z', '.000Z'));
  return result;
};
/** @param {number} ms */
const dayText = (ms) => new Date(ms).toISOString().slice(0, 10);
/** @param {Period} period */
const days = (period) => {
  keys(period, 'start end_exclusive');
  const start = instant(period.start + 'T00:00:00Z'), end = instant(period.end_exclusive + 'T00:00:00Z');
  require(end >= start && end - start <= 31 * 86400000);
  return Array.from({ length: (end - start) / 86400000 }, (_, i) => dayText(start + i * 86400000));
};
/** @template {keyof HTMLElementTagNameMap} T @param {T} tag @param {string} [text] @param {string} [className] */
const element = (tag, text, className) => {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
};
/** @param {string | number | null} value */
const money = (value) => {
  if (value === null) return 'Unavailable';
  const number = Number(value);
  if (number !== 0 && Math.abs(number) < .005) return (number < 0 ? '−' : '') + '<$0.01';
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(number);
};
/** @param {string} value */
const when = (value) => new Date(value).toLocaleString('en-US', { timeZone: 'UTC', dateStyle: 'medium', timeStyle: 'short' }) + ' UTC';
/** @param {Period} period */
const range = (period) => period.start === period.end_exclusive ? 'No completed days this month' : `${period.start} to ${dayText(Date.parse(period.end_exclusive) - 86400000)}`;

/** @param {unknown} input @param {string} environment @returns {Snapshot} */
export function validate(input, environment = expectedEnvironment) {
  // Validate external JSON with the existing contract before returning it.
  const snapshot = /** @type {Snapshot} */ (input);
  keys(snapshot, 'schema_version kind environment scope currency periods requested published_at attempt sources month_to_date daily aws_services aws_environments');
  require(['development', 'production'].includes(environment) && snapshot.environment === environment);
  require(snapshot.schema_version === 1 && snapshot.kind === 'billing-costs' && snapshot.currency === 'USD');
  require((environment === 'production' ? ['aws-production+aws-development+openai-organization'] : ['aws-development', 'aws-development+openai-organization']).includes(snapshot.scope));
  const published = instant(snapshot.published_at);
  require(published <= Date.now());
  keys(snapshot.periods, 'month_to_date last_30_days');
  const end = snapshot.requested.end_exclusive, month = end.slice(0, 7) + '-01';
  const trendStart = dayText(instant(end + 'T00:00:00Z') - 30 * 86400000);
  require(end <= snapshot.published_at.slice(0, 10));
  const wanted = days(snapshot.requested);
  require(snapshot.requested.start === [month, trendStart].sort()[0]);
  for (const [name, start] of [['month_to_date', month], ['last_30_days', trendStart]]) {
    days(snapshot.periods[name]);
    require(snapshot.periods[name].start === start && snapshot.periods[name].end_exclusive === end);
  }
  const ids = environment === 'production' ? ['aws_production', 'aws_development', 'openai'] : ['aws_development', 'openai'];
  keys(snapshot.sources, ids.join(' '));
  keys(snapshot.attempt, 'at status sources');
  keys(snapshot.attempt.sources, ids.join(' '));
  require(instant(snapshot.attempt.at) >= published && instant(snapshot.attempt.at) <= Date.now());
  for (const id of ids) {
    const source = snapshot.sources[id];
    keys(source, 'status scope currency requested retrieved_at finalized_through estimated daily aws_services aws_environments');
    const disabled = snapshot.scope === 'aws-development' && id === 'openai';
    const allowed = disabled ? ['not_configured'] : ['available', 'unavailable'];
    require(allowed.includes(source.status) && allowed.includes(snapshot.attempt.sources[id]));
    require(source.scope === scopes[id] && source.currency === 'USD' && source.finalized_through === null);
    require(JSON.stringify(days(source.requested)) === JSON.stringify(wanted));
    require(source.requested.start === snapshot.requested.start && source.requested.end_exclusive === end);
    require(['daily', 'aws_services', 'aws_environments'].every(field => Array.isArray(source[/** @type {'daily' | 'aws_services' | 'aws_environments'} */ (field)])));
    if (source.status !== 'available') {
      require(source.retrieved_at === null && source.estimated === null && !source.daily.length && !source.aws_services.length && !source.aws_environments.length);
      continue;
    }
    require(instant(source.retrieved_at) <= published && source.retrieved_at.slice(0, 10) >= end);
    require(id.startsWith('aws_') ? typeof source.estimated === 'boolean' : source.estimated === null);
    require(JSON.stringify(source.daily.map(row => row.date)) === JSON.stringify(wanted));
    source.daily.forEach(row => { keys(row, 'date usd'); units(row.usd); });
    for (const field of ['aws_services', 'aws_environments']) {
      const rows = source[/** @type {'aws_services' | 'aws_environments'} */ (field)];
      require(new Set(rows.map(row => row.label)).size === rows.length);
      for (const row of rows) {
        keys(row, 'label usd'); units(row.usd);
        require(field === 'aws_environments' ? Object.hasOwn(colors, row.label) : serviceLabels.includes(row.label));
      }
      require(id.startsWith('aws_') ? sum(rows.map(row => row.usd)) === sum(source.daily.filter(row => row.date >= month).map(row => row.usd)) : !rows.length);
    }
  }
  require(snapshot.attempt.status === (Object.values(snapshot.attempt.sources).includes('unavailable') ? 'failed' : 'succeeded'));
  const aws = ids.filter(id => id.startsWith('aws_')).map(id => snapshot.sources[id]);
  const openai = [snapshot.sources.openai];
  /** @param {Source[]} sources @param {string} [day] */
  const subtotal = (sources, day) => sources.every(source => source.status === 'available') ? sum(sources.flatMap(source => source.daily.filter(row => day ? row.date === day : row.date >= month).map(row => row.usd))) : null;
  /** @param {Totals} row @param {string} [day] */
  const checkTotals = (row, day) => {
    const a = subtotal(aws, day), b = subtotal(openai, day);
    matches(row.aws, a); matches(row.openai, b); matches(row.total, a !== null && b !== null ? a + b : null);
  };
  keys(snapshot.month_to_date, 'aws openai total'); checkTotals(snapshot.month_to_date);
  require(Array.isArray(snapshot.daily) && JSON.stringify(snapshot.daily.map(row => row.date)) === JSON.stringify(days(snapshot.periods.last_30_days)));
  snapshot.daily.forEach(row => { keys(row, 'date aws openai total'); checkTotals(row, row.date); });
  for (const field of ['aws_services', 'aws_environments']) {
    /** @type {Map<string, bigint>} */
    const amounts = new Map();
    aws.filter(source => source.status === 'available').flatMap(source => source[/** @type {'aws_services' | 'aws_environments'} */ (field)]).forEach(row => amounts.set(row.label, (amounts.get(row.label) ?? 0n) + units(row.usd)));
    require(Array.isArray(snapshot[/** @type {'aws_services' | 'aws_environments'} */ (field)]) && snapshot[/** @type {'aws_services' | 'aws_environments'} */ (field)].length === amounts.size);
    const labels = new Set();
    for (const row of snapshot[/** @type {'aws_services' | 'aws_environments'} */ (field)]) {
      keys(row, 'label usd'); require(!labels.has(row.label) && amounts.has(row.label));
      matches(row.usd, amounts.get(row.label)); labels.add(row.label);
    }
  }
  return snapshot;
}

/** @param {Day[]} rows */
function chart(rows) {
  const host = $('trend'); host.replaceChildren();
  if (!rows.some(row => row.aws !== null || row.openai !== null)) {
    host.append(element('p', 'Daily amounts unavailable.', 'chart-empty')); return;
  }
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  const width = Math.max(240, host.clientWidth), step = (width - 68) / rows.length;
  svg.setAttribute('viewBox', `0 0 ${width} 240`); svg.setAttribute('class', 'chart');
  svg.setAttribute('role', 'img'); svg.setAttribute('aria-label', 'Daily AWS and OpenAI costs. Credits are below zero. Use the daily table for amounts and missing sources.');
  /** @param {string} tag @param {Record<string, string | number | null>} attrs @param {string} [text] */
  const add = (tag, attrs, text) => {
    const node = document.createElementNS(svg.namespaceURI, tag);
    for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, String(value));
    if (text !== undefined) node.textContent = text;
    svg.append(node); return node;
  };
  const upper = Math.max(0, ...rows.map(row => Math.max(0, Number(row.aws)) + Math.max(0, Number(row.openai))));
  const lower = Math.min(0, ...rows.map(row => Math.min(0, Number(row.aws)) + Math.min(0, Number(row.openai))));
  const span = upper - lower || 1;
  /** @param {number} value */
  const y = value => 196 - (value - lower) / span * 176;
  for (let i = 0; i <= 4; i++) {
    const value = lower + span * i / 4;
    add('line', { x1: 56, x2: width - 4, y1: y(value), y2: y(value), stroke: '#e8ecf1' });
    const label = value !== 0 && Math.abs(value) < .01 ? '$' + value.toExponential(1) : money(value.toString());
    add('text', { x: 49, y: y(value) + 4, 'text-anchor': 'end' }, label);
  }
  add('line', { x1: 56, x2: width - 4, y1: y(0), y2: y(0), stroke: '#8090a4' });
  rows.forEach((row, index) => {
    const x = 60 + index * step;
    let positive = 0, negative = 0;
    for (const [provider, color] of [['aws', '#175ccd'], ['openai', '#176746']]) {
      if (row[/** @type {keyof Totals} */ (provider)] === null) continue;
      const value = Number(row[/** @type {keyof Totals} */ (provider)]);
      const start = value < 0 ? negative : positive;
      const bar = add('rect', { x, y: Math.min(y(start), y(start + value)), width: step * .65, height: Math.abs(value) / span * 176, fill: color, 'data-date': row.date, 'data-provider': provider, 'data-usd': row[/** @type {keyof Totals} */ (provider)] });
      const title = document.createElementNS(svg.namespaceURI, 'title'); title.textContent = `${row.date} ${provider}: ${money(row[/** @type {keyof Totals} */ (provider)])}`; bar.append(title);
      if (value < 0) negative += value; else positive += value;
    }
    if ((width < 500 ? [0, 13, 29] : [0, 6, 13, 20, 29]).includes(index)) add('text', { x: x + step * .3, y: 225, 'text-anchor': index === 29 ? 'end' : 'middle' }, row.date.slice(5));
  });
  host.append(svg);
}

/** @type {Snapshot} */
let snapshot;
let failedRefresh = false, refreshing = false;
function notice() {
  const messages = [];
  if (failedRefresh) messages.push(snapshot ? 'Browser refresh failed. Showing the last valid snapshot.' : 'The billing snapshot could not be loaded. No complete total is available.');
  if (snapshot?.attempt.status === 'failed') messages.push(`Daily refresh failed at ${when(snapshot.attempt.at)}. Last valid amounts are retained where available.`);
  if (snapshot && Date.now() - Date.parse(snapshot.published_at) > 48 * 3600000) messages.push('Stale: publication is over 48 hours old.');
  if (snapshot?.month_to_date.total === null) messages.push(snapshot.scope === 'aws-development' ? 'This earlier snapshot contains development AWS only. Awaiting the first OpenAI billing publication.' : 'A required billing source is unavailable. Available source subtotals are shown; the combined total is withheld.');
  $('state-notice').hidden = !messages.length; set('state-notice', messages.join(' '));
}
function render() {
  const mtd = snapshot.month_to_date;
  for (const provider of ['total', 'aws', 'openai']) {
    set(provider, money(mtd[/** @type {keyof Totals} */ (provider)])); $(provider).classList.toggle('unavailable', mtd[/** @type {keyof Totals} */ (provider)] === null);
  }
  set('total-note', mtd.total === null ? 'Combined total unavailable' : expectedEnvironment === 'development' ? 'Development AWS + OpenAI organization' : 'AWS + OpenAI API · Same reporting period');
  set('aws-note', expectedEnvironment === 'development' ? 'Development account only · Unblended cost' : 'Two accounts · Unblended cost');
  set('openai-note', 'Organization-wide · Provider-reported');
  ($('coverage-label') ?? /** @type {HTMLElement} */ (document.querySelector('.context-line > span'))).textContent = expectedEnvironment === 'development' ? 'Development AWS account plus organization-wide OpenAI costs. OpenAI includes all environments.' : 'Includes production, development, shared infrastructure, and unallocated spend.';
  set('period-label', range(snapshot.periods.month_to_date));
  set('trend-period', '30 completed days · ' + range(snapshot.periods.last_30_days));
  set('publication-label', 'Published ' + when(snapshot.published_at));
  set('source-subtotals', Object.entries(snapshot.sources).map(([id, source]) => {
    const charge = source.status === 'available' ? money(Number(sum(source.daily.filter(row => row.date >= snapshot.periods.month_to_date.start).map(row => row.usd))) / 1e30) : 'Unavailable';
    return `${names[id]}: ${charge}`;
  }).join(' · '));
  set('retrieval-times', Object.entries(snapshot.sources).map(([id, source]) => `${names[id]}: ${source.retrieved_at ? 'retrieved ' + when(source.retrieved_at) : 'unavailable'}${source.estimated === true ? ' (AWS marked estimated)' : ''}`).join('; ') + '. Provider-confirmed finalized-through date: unavailable.');
  chart(snapshot.daily);
  $('daily-rows').replaceChildren();
  for (const day of snapshot.daily) {
    const row = element('tr'), label = element('th', day.date); label.scope = 'row'; row.append(label);
    for (const field of ['aws', 'openai', 'total']) { const cell = element('td', money(day[/** @type {keyof Totals} */ (field)])); cell.dataset.usd = day[/** @type {keyof Totals} */ (field)] ?? ''; row.append(cell); }
    $('daily-rows').append(row);
  }
  $('services').replaceChildren();
  const max = Math.max(0, ...snapshot.aws_services.map(row => Math.abs(Number(row.usd))));
  for (const service of [...snapshot.aws_services].sort((a, b) => Number(b.usd) - Number(a.usd))) {
    const row = element('div', undefined, 'driver'), line = element('div', undefined, 'driver-line'), track = element('div', undefined, 'track'), fill = element('div', undefined, 'fill');
    line.append(element('span', service.label), element('strong', money(service.usd)));
    // Signed amounts remain in the labels; bars are omitted for credit categories.
    fill.style.width = (max ? Math.max(0, Number(service.usd)) / max * 100 : 0) + '%';
    track.setAttribute('aria-hidden', 'true'); track.append(fill); row.append(line, track); $('services').append(row);
  }
  if (!snapshot.aws_services.length) $('services').append(element('p', 'No service amounts available for this period.', 'fine'));
  $('environments').replaceChildren(); $('allocation').replaceChildren();
  const allocationTotal = snapshot.aws_environments.reduce((n, row) => n + Number(row.usd), 0);
  const showAllocation = allocationTotal > 0 && snapshot.aws_environments.every(row => Number(row.usd) >= 0);
  $('allocation').hidden = !showAllocation;
  for (const env of snapshot.aws_environments) {
    const row = element('tr'), label = element('th'), swatch = element('span', undefined, 'swatch');
    swatch.style.background = colors[env.label]; swatch.setAttribute('aria-hidden', 'true'); label.scope = 'row';
    label.append(swatch, env.label[0].toUpperCase() + env.label.slice(1)); row.append(label, element('td', money(env.usd))); $('environments').append(row);
    if (showAllocation) { const segment = element('span'); segment.style.width = Number(env.usd) / allocationTotal * 100 + '%'; segment.style.background = colors[env.label]; $('allocation').append(segment); }
  }
  notice();
}
async function refresh() {
  if (refreshing) return;
  refreshing = true;
  try {
    const response = await fetch('/costs.json', { cache: 'no-store', redirect: 'error', signal: AbortSignal.timeout(15000) });
    require(response.ok);
    const body = await response.text(); require(body.length <= 2 * 1024 * 1024);
    snapshot = validate(JSON.parse(body)); failedRefresh = false; render();
  } catch {
    failedRefresh = true;
    if (!snapshot) { for (const id of ['total', 'aws', 'openai']) { set(id, 'Unavailable'); $(id).classList.add('unavailable'); } set('total-note', 'No valid billing snapshot'); set('trend', 'Daily amounts unavailable.'); }
    notice();
  } finally { refreshing = false; }
}
set('deployment', expectedEnvironment.toUpperCase() + ' · BILLING');
window.addEventListener('resize', () => { if (snapshot) chart(snapshot.daily); });
window.addEventListener('focus', refresh);
document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
setInterval(refresh, 5 * 60000);
const serviceLabels = ["AWS CloudTrail", "AWS Cost Explorer", "AWS Glue", "AWS Key Management Service", "AWS Lambda", "AWS Systems Manager", "AWS WAF", "Amazon API Gateway", "Amazon Athena", "Amazon Bedrock", "Amazon Bedrock AgentCore", "Amazon CloudFront", "Amazon Data Firehose", "Amazon DynamoDB", "Amazon Elastic Compute Cloud - Compute", "Amazon EventBridge", "Amazon Kinesis Firehose", "Amazon Relational Database Service", "Amazon Route 53", "Amazon Simple Notification Service", "Amazon Simple Queue Service", "Amazon Simple Storage Service", "Amazon Virtual Private Cloud", "AmazonCloudWatch", "EC2 - Other", "Other AWS services", "Tax"];
await refresh();
