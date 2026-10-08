import assert from 'node:assert/strict';
import { test } from 'node:test';
import { isPublicPath } from './publicPaths.ts';

test('production health is public, look-alikes are protected', () => {
  assert.equal(isPublicPath('/health'), true);
  assert.equal(isPublicPath('/health/private'), false);
});

for (const status of ['healthy', 'degraded', 'unhealthy']) {
  test(`frontend reflects backend ${status} without private payload`, async () => {
    const { productionHealth } = await import('./productionHealth.ts');
    const result = await productionHealth('http://backend:8000', async () => Response.json({ status, secret: 'PRIVATE' }, { status: status === 'unhealthy' ? 503 : 200 }));
    assert.equal(result.body.status, status);
    assert.equal(result.code, status === 'unhealthy' ? 503 : 200);
    assert.equal(JSON.stringify(result).includes('PRIVATE'), false);
  });
}
test('unreachable backend is unhealthy', async () => {
  const { productionHealth } = await import('./productionHealth.ts');
  const result = await productionHealth('http://backend:8000', async () => { throw Error('PRIVATE'); });
  assert.equal(result.code, 503);
  assert.equal(result.body.backend.reachable, false);
  assert.equal(JSON.stringify(result).includes('PRIVATE'), false);
});
test('login redirect or invalid status is not healthy', async () => {
  const { productionHealth } = await import('./productionHealth.ts');
  const result = await productionHealth('http://backend:8000', async () => new Response('<html>login</html>'));
  assert.equal(result.code, 503);
});
