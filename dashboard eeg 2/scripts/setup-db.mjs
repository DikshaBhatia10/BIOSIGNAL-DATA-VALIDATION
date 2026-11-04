// Creates the tables and loads the EEG QC data into PostgreSQL.
import { readFileSync } from 'node:fs';
import pg from 'pg';

const url = process.env.DATABASE_URL;
if (!url) {
  console.error('DATABASE_URL is not set. Copy .env.example to .env.local and edit it.');
  process.exit(1);
}
const client = new pg.Client({ connectionString: url });
await client.connect();
await client.query(readFileSync(new URL('../db/schema.sql', import.meta.url), 'utf8'));
const { rows } = await client.query('SELECT COUNT(*)::int AS n FROM recordings');
console.log(`Database ready: ${rows[0].n} recordings loaded.`);
await client.end();
