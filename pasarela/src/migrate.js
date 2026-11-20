import { crearDb } from './db.js';

const url = process.env.DATABASE_URL;
if (!url) throw new Error('Falta DATABASE_URL');
const db = crearDb(url);
await db.migrar();
await db.cerrar();
console.log('Esquema aplicado.');
