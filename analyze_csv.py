import csv, sys
from collections import Counter
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

with open('soniqtools-batch-2026-07-04.csv', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    rows = list(reader)

verdicts = Counter(r['Verdict'] for r in rows)
formats  = Counter(r['Format'] for r in rows)
total = len(rows)

bad = ['Upsampled / Transcoded', 'Lossy Transcode', 'Low-Bitrate Lossy', 'Possibly Upsampled', 'Error']
bad_count = sum(verdicts.get(v, 0) for v in bad)
good_count = total - bad_count

print(f'Total tracks: {total}')
print(f'Problems (need healing): {bad_count} ({bad_count/total*100:.1f}%)')
print(f'Fine (clean): {good_count} ({good_count/total*100:.1f}%)')
print()
print('=== VERDICT BREAKDOWN ===')
for v, c in sorted(verdicts.items(), key=lambda x: -x[1]):
    mark = 'BAD' if v in bad else ' OK'
    print(f'  {mark}  {v}: {c} ({c/total*100:.1f}%)')
print()
print('=== FORMAT ===')
for fmt, c in sorted(formats.items(), key=lambda x: -x[1]):
    print(f'  {fmt}: {c}')
print()

# Tracks that are still bad (AAC/M4A or Error)
m4a_bad = [r for r in rows if r['Format'] in ('AAC', '') and r['Verdict'] in bad]
print(f'Non-FLAC still flagged: {len(m4a_bad)}')
for r in m4a_bad[:15]:
    print(f'  [{r["Verdict"]}] {r["File"]}')

# Healer progress: the old CSV (2026-07-01) against the new one (2026-07-04)
print()
print('=== COMPARED WITH THE OLD CSV ===')
try:
    with open('soniqtools-batch-2026-07-01.csv', encoding='utf-8') as f:
        old_rows = list(csv.DictReader(f))
    old_verdicts = Counter(r['Verdict'] for r in old_rows)
    old_bad = sum(old_verdicts.get(v, 0) for v in bad)
    print(f'CSV 2026-07-01: {len(old_rows)} tracks, {old_bad} flagged ({old_bad/len(old_rows)*100:.1f}%)')
    print(f'CSV 2026-07-04: {total} tracks, {bad_count} flagged ({bad_count/total*100:.1f}%)')
    healed = old_bad - bad_count
    print(f'Down by: {healed} tracks ({healed/old_bad*100:.1f}% of what was flagged before)')
except FileNotFoundError:
    print('The old CSV is not there, skipping the comparison.')
