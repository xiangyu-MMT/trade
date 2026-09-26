import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

try {
  const runtime = process.argv[2];
  const input = JSON.parse(readFileSync(0, 'utf8'));
  if (typeof input.data !== 'string' || input.data.length > 17000000) throw Error('Parquet payload size invalid');
  const buffer = Buffer.from(input.data, 'base64');
  if (buffer.subarray(0, 4).toString() !== 'PAR1') throw Error('Invalid Parquet header');
  const file = buffer.buffer.slice(buffer.byteOffset, buffer.byteOffset + buffer.byteLength);
  const parser = await import(pathToFileURL(resolve(runtime, 'node_modules/hyparquet/src/index.js')).href);
  const { compressors } = await import(pathToFileURL(resolve(runtime, 'node_modules/hyparquet-compressors/src/index.js')).href);
  const meta = await parser.parquetMetadataAsync(file);
  if (Number(meta.num_rows) > 50000) throw Error('Stock directory exceeds row limit');
  const rows = await parser.parquetReadObjects({ file, compressors, columns: ['date', 'symbol', 'asset_type', 'close', 'volume'] });
  process.stdout.write(JSON.stringify({ rows }, (_, value) => typeof value === 'bigint' ? Number(value) : value));
} catch (error) {
  process.stdout.write(JSON.stringify({ error: String(error.message || error) }));
  process.exitCode = 1;
}
