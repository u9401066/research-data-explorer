-- Independent SQLite oracle for the predeclared synthetic fixture.
-- Each event table is aggregated separately; no raw three-table join is used.
WITH observed AS (
  SELECT p.*,
    (SELECT COUNT(*) FROM labs l WHERE l.site=p.site AND l.pid=p.pid) AS matched_n,
    (SELECT COUNT(*) FROM labs l WHERE l.site=p.site AND l.pid=p.pid
      AND julianday(l.taken_at) BETWEEN julianday(p.index_at)-7 AND julianday(p.index_at)) AS window_n,
    (SELECT COUNT(*) FROM labs l WHERE l.site=p.site AND l.pid=p.pid
      AND julianday(l.taken_at) BETWEEN julianday(p.index_at)-7 AND julianday(p.index_at)
      AND julianday(l.known_at)<=julianday(p.index_at)) AS available_n,
    (SELECT AVG(CAST(l.value AS REAL)) FROM labs l WHERE l.site=p.site AND l.pid=p.pid
      AND julianday(l.taken_at) BETWEEN julianday(p.index_at)-7 AND julianday(p.index_at)
      AND julianday(l.known_at)<=julianday(p.index_at)) AS lab_mean,
    (SELECT COUNT(*) FROM meds m WHERE m.site=p.site AND m.pid=p.pid) AS drug_count
  FROM people p WHERE CAST(p.age AS REAL)>=18
)
SELECT site, pid, age, index_at, lab_exported,
  CASE WHEN available_n>0 THEN 'matched'
    WHEN lab_exported='no' THEN 'not_exported'
    WHEN window_n>0 THEN 'not_available'
    WHEN matched_n>0 THEN 'outside_window'
    WHEN lab_exported='yes' THEN 'no_record'
    ELSE 'unknown_coverage' END AS _rde_labs_status,
  CASE WHEN available_n>0 THEN available_n
    WHEN lab_exported='yes' AND window_n=0 THEN 0
    ELSE NULL END AS lab_count,
  lab_mean,
  CASE WHEN drug_count>0 THEN 'matched' ELSE 'no_record' END AS _rde_meds_status,
  drug_count
FROM observed ORDER BY site,pid;
