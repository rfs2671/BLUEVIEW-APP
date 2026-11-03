# Step 0a output: box_beam_designations.csv / .md from work/box_beam_extract.json (text layer of ST - 7.29.26.pdf p6..p10). Read-only.
import json, csv, re, collections
x = json.load(open('work/box_beam_extract.json')); rows = []
for n in x['notes']:
    if 'BOX BEAM' in n['quote']:
        m = re.search(r'\(2\) (800S162-\d+) BOX BEAM', n['quote']); rows.append(dict(kind='note4', sheet=n['sheet'], pdf_page=n['pdf_page'], designation=m.group(1), quote=n['quote'], x_pt=n['x0'], y_pt=n['y0']))
for l in x['labels']: rows.append(dict(kind='label', sheet=l['sheet'], pdf_page=l['pdf_page'], designation=l['quote'].replace('(2) ', ''), quote=l['quote'], x_pt=l['x0'], y_pt=l['y0']))
rows.append(dict(kind='note4_absent', sheet='S-101.00', pdf_page=5, designation='', quote='S-101 has no note 4 / no box beam legend (inventory b1)', x_pt='', y_pt=''))
with open('box_beam_designations.csv', 'w', encoding='utf8', newline='') as f: w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
n4 = [r for r in rows if r['kind'] == 'note4']; lab = collections.Counter((r['sheet'], r['designation']) for r in rows if r['kind'] == 'label')
md = ['# Box beam designations as printed (ST - 7.29.26.pdf; text layer, quoted exactly)', '', '| sheet | PDF page | note 4 quote | designation |', '|---|---|---|---|']
for r in n4: md.append('| %s | %d | "%s" | %s |' % (r['sheet'], r['pdf_page'], r['quote'], r['designation']))
md += ['', '**-54 vs -118 resolved:** S-102, S-103, S-105 and S-106 print "(2) 800S162-54 BOX BEAM U.O.N."; **only S-104 (PDF p8, FLOOR_4) prints "(2) 800S162-118 BOX BEAM U.O.N."**. The inventory had checked S-102 and S-106 only. Each note-4 beam in the model takes the designation of its own sheet (verify_v10.py checks all 31 per track).', '', '## Labelled beams (own label, not a box-beam note)', 'None of the labels prints "800S162". Labels are of the form "(2) nSWm"; "SW" is not defined on S-001 and there is no beam schedule ("BOX BEAM SEE SCHED." on S-301 points to nothing).', '', '| sheet | label as printed | count of that label on the sheet |', '|---|---|---|']
for (s, d), c in sorted(lab.items()): md.append('| %s | (2) %s | %d |' % (s, d, c))
md += ['', 'Geometry rule (Roy): depth = the "800" of the note-4 designation = 8 in; individual members at plan position (the plan band is split into the 2 printed members); label-governed beams get an outline only (depth not printed).']
open('box_beam_designations.md', 'w', encoding='utf8').write('\n'.join(md))
print('\n'.join(md))
