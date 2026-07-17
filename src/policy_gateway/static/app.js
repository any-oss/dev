const $ = (id) => document.getElementById(id);

async function jsonFetch(url, options = {}) {
  const response = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  const text = await response.text();
  const body = text ? JSON.parse(text) : {};
  if (!response.ok) throw new Error(body.detail || body.error || response.statusText);
  return body;
}

async function refresh() {
  try {
    const health = await jsonFetch('/health');
    $('state').textContent = health.state;
    const metrics = await fetch('/metrics');
    if (metrics.ok) {
      const lines = Object.fromEntries((await metrics.text()).trim().split('\n').map((line) => {
        const [name, value] = line.split(' ');
        return [name.replace(/\{.*\}/, ''), value];
      }));
      $('p95').textContent = `${lines.policy_gateway_p95_latency_ms || '0'} ms`;
      $('error-rate').textContent = lines.policy_gateway_error_rate || '0';
      $('qps').textContent = lines.policy_gateway_qps || '0';
    }
  } catch (error) {
    $('output').textContent = `refresh failed: ${error.message}`;
  }
}

$('ingest-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  try {
    const body = await jsonFetch('/api/v1/ingest', {
      method: 'POST',
      body: JSON.stringify({ latency_ms: Number($('latency').value), status_code: Number($('status-code').value) }),
    });
    $('output').textContent = JSON.stringify(body, null, 2);
    await refresh();
  } catch (error) {
    $('output').textContent = error.message;
  }
});

$('dispatch-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  try {
    const body = await jsonFetch('/api/v1/dispatch', {
      method: 'POST',
      body: JSON.stringify({ payload: { prompt: $('prompt').value }, mem_kb: Number($('mem-kb').value) }),
    });
    $('output').textContent = JSON.stringify(body, null, 2);
    await refresh();
  } catch (error) {
    $('output').textContent = error.message;
  }
});

refresh();
setInterval(refresh, 5000);
