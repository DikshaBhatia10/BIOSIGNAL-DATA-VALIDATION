import Dashboard from '@/components/Dashboard';
import { getRecordings } from '@/lib/data';

export const dynamic = 'force-dynamic';

export default async function Page() {
  try {
    const recordings = await getRecordings();
    if (recordings.length === 0) throw new Error('The recordings table is empty.');
    return <Dashboard recordings={recordings} />;
  } catch (e) {
    return (
      <main className="wrap">
        <div className="panel">
          <p className="kicker">DATABASE NOT READY</p>
          <h2>Could not load QC data from PostgreSQL</h2>
          <p className="muted mono">{(e as Error).message}</p>
          <p className="muted">
            Check DATABASE_URL in <span className="mono">.env.local</span>, make sure PostgreSQL is running, then run{' '}
            <span className="mono red">npm run db:setup</span> and refresh.
          </p>
        </div>
      </main>
    );
  }
}
