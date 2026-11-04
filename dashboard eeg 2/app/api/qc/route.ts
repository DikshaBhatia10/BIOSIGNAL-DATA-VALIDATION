import { NextResponse } from 'next/server';
import { getRecordings } from '@/lib/data';

export const dynamic = 'force-dynamic';

export async function GET() {
  try {
    return NextResponse.json(await getRecordings());
  } catch (e) {
    return NextResponse.json({ error: (e as Error).message }, { status: 500 });
  }
}
