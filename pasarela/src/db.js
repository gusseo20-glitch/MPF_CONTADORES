import pg from 'pg';
import { readFile } from 'node:fs/promises';

export function crearDb(databaseUrl) {
  const pool = new pg.Pool({ connectionString: databaseUrl, max: 10 });
  pool.on('error', (e) => console.error('[db] error en conexión inactiva:', e.message));

  return {
    pool,
    query: (texto, valores) => pool.query(texto, valores),
    // Ejecuta fn dentro de una transacción; si lanza, se deshace todo.
    async tx(fn) {
      const c = await pool.connect();
      try {
        await c.query('BEGIN');
        const r = await fn(c);
        await c.query('COMMIT');
        return r;
      } catch (e) {
        await c.query('ROLLBACK').catch(() => {});
        throw e;
      } finally {
        c.release();
      }
    },
    async migrar() {
      const sql = await readFile(new URL('../sql/schema.sql', import.meta.url), 'utf8');
      await pool.query(sql);
    },
    cerrar: () => pool.end(),
  };
}
