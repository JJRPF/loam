-- Round 8 (GH-38) phase 1: seed heat. A visit of an activity imported from the admin's Garmin
-- export (activities.source = 'garmin_export') is seed heat; seed heat is public on trail-class
-- edges only (decay.heat_is_public). edge_heat.is_public is rebuilt by the next recalculation.
ALTER TABLE activity_edge_visits ADD COLUMN IF NOT EXISTS is_seed BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE edge_heat ADD COLUMN IF NOT EXISTS has_seed BOOLEAN NOT NULL DEFAULT FALSE;

UPDATE activity_edge_visits v SET is_seed = TRUE
FROM activities a
WHERE a.id = v.activity_id AND a.source = 'garmin_export' AND NOT v.is_seed;
