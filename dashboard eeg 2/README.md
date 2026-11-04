# EEG Pipeline QC Dashboard

Next.js 14 + TypeScript + PostgreSQL. Black / grey / red theme with the MRI scan as a faded background.

## Run it (Windows, cmd)

1. Install Node.js 20.6 or newer and PostgreSQL.
2. Create an empty database:
   `createdb -U postgres eeg_qc`
   (or create `eeg_qc` in pgAdmin)
3. In this folder:
   ```
   copy .env.example .env.local
   notepad .env.local          (set your PostgreSQL password in DATABASE_URL)
   npm install
   npm run db:setup            (creates tables and loads the EEG QC data)
   npm run dev
   ```
4. Open http://localhost:3000

## Tweaks

- Background strength: `--bg-opacity` at the top of `app/globals.css` (0 to 1).
- JSON of all data: http://localhost:3000/api/qc
- To load new pipeline results, add rows to `recordings` and `qc_checks` (see `db/schema.sql` for the shape).
