-- Transit stop catchment analysis. PostGIS 3.4.
-- stops.geom  geometry(Point, 4326)
-- routes.geom geometry(LineString, 4326)
-- parcels.geom geometry(MultiPolygon, 4326)
-- CREATE INDEX stops_geom_gix   ON stops   USING GIST (geom);
-- CREATE INDEX parcels_geom_gix ON parcels USING GIST (geom);

-- Every stop within 500 m of a given point.
SELECT s.id, s.name
  FROM stops s
 WHERE ST_Distance(
           s.geom,
           ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)
       ) < 500
 ORDER BY s.name;

-- Parcels touched by a 250 m corridor either side of a route.
SELECT p.parcel_ref, p.owner_name
  FROM parcels p
  JOIN routes r ON r.id = :route_id
 WHERE ST_Intersects(p.geom, ST_Buffer(r.geom, 0.0025));

-- Total walkable land area inside the corridor, in hectares.
SELECT SUM(ST_Area(ST_Intersection(p.geom, ST_Buffer(r.geom, 0.0025)))) / 10000
       AS hectares
  FROM parcels p
  JOIN routes r ON r.id = :route_id
 WHERE p.land_use = 'residential'
   AND ST_Intersects(p.geom, ST_Buffer(r.geom, 0.0025));
